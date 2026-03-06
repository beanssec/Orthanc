"""OpenSanctions integration service.

Downloads the OpenSanctions bulk FtM dataset, upserts into sanctions_entities,
and performs fuzzy trigram matching against platform entities.

IMPORTANT: The bulk download (~200 MB) is NEVER triggered on startup.
           It only runs when explicitly triggered via the API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models.sanctions import EntitySanctionsMatch, SanctionsEntity

logger = logging.getLogger("orthanc.sanctions")

OPENSANCTIONS_URL = (
    "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
)

# Entity schema types we care about
ACCEPTED_SCHEMAS = {
    "Person",
    "Organization",
    "LegalEntity",
    "Company",
    "Vessel",
    "Aircraft",
}

# Map FtM schema → our short entity_type label
SCHEMA_MAP = {
    "Person": "person",
    "Organization": "organization",
    "LegalEntity": "organization",
    "Company": "organization",
    "Vessel": "vessel",
    "Aircraft": "aircraft",
}

BATCH_SIZE = 1_000


class SanctionsService:
    """Singleton service for OpenSanctions data management and entity matching."""

    def __init__(self) -> None:
        self._download_lock = asyncio.Lock()
        self._is_downloading = False
        self._last_download_error: str | None = None

    # ── Status ────────────────────────────────────────────────────────────────

    async def status(self) -> dict:
        """Return database statistics."""
        async with AsyncSessionLocal() as db:
            count_result = await db.execute(
                text("SELECT COUNT(*) FROM sanctions_entities")
            )
            entity_count = count_result.scalar() or 0

            match_count_result = await db.execute(
                text("SELECT COUNT(*) FROM entity_sanctions_matches")
            )
            match_count = match_count_result.scalar() or 0

            last_updated_result = await db.execute(
                text("SELECT MAX(updated_at) FROM sanctions_entities")
            )
            last_updated = last_updated_result.scalar()

        return {
            "entity_count": entity_count,
            "match_count": match_count,
            "last_updated": last_updated.isoformat() if last_updated else None,
            "is_downloading": self._is_downloading,
            "last_download_error": self._last_download_error,
        }

    # ── Download & upsert ─────────────────────────────────────────────────────

    async def trigger_download(self) -> dict:
        """Start a background download if one is not already running."""
        if self._is_downloading:
            return {"status": "already_running", "message": "Download already in progress"}

        asyncio.create_task(self._download_and_upsert())
        return {"status": "started", "message": "Sanctions data download started in background"}

    async def _download_and_upsert(self) -> None:
        """Stream-download the OpenSanctions FtM bulk file and upsert into DB."""
        if self._is_downloading:
            return

        async with self._download_lock:
            self._is_downloading = True
            self._last_download_error = None
            logger.info("Starting OpenSanctions bulk download from %s", OPENSANCTIONS_URL)

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".jsonl", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)

            # Stream download — write chunks directly, don't buffer in memory
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", OPENSANCTIONS_URL) as response:
                    response.raise_for_status()
                    downloaded_bytes = 0
                    last_logged = 0
                    with tmp_path.open("wb") as fout:
                        async for chunk in response.aiter_bytes(chunk_size=65_536):
                            fout.write(chunk)
                            downloaded_bytes += len(chunk)
                            mb = downloaded_bytes // (10 * 1024 * 1024)
                            if mb > last_logged:
                                last_logged = mb
                                logger.info(
                                    "Downloaded %.0f MB…",
                                    downloaded_bytes / (1024 * 1024),
                                )

            logger.info(
                "Download complete (%.1f MB). Parsing and upserting…",
                tmp_path.stat().st_size / (1024 * 1024),
            )
            await self._parse_and_upsert(tmp_path)

        except Exception as exc:
            self._last_download_error = str(exc)
            logger.error("Sanctions download/upsert failed: %s", exc, exc_info=True)
        finally:
            async with self._download_lock:
                self._is_downloading = False
            # Clean up temp file
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    async def _parse_and_upsert(self, path: Path) -> None:
        """Parse newline-delimited FtM JSON and batch-upsert into DB."""
        batch: list[dict] = []
        total_processed = 0
        total_skipped = 0

        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    total_skipped += 1
                    continue

                schema = obj.get("schema", "")
                if schema not in ACCEPTED_SCHEMAS:
                    total_skipped += 1
                    continue

                props = obj.get("properties", {})

                # Extract aliases from various alias properties
                aliases: list[str] = []
                for alias_key in ("alias", "weakAlias", "previousName"):
                    aliases.extend(props.get(alias_key, []))
                aliases = list(set(a for a in aliases if a))

                # Countries
                countries: list[str] = list(
                    set(props.get("country", []) + props.get("nationality", []))
                )

                # Datasets
                datasets: list[str] = obj.get("datasets", [])

                record = {
                    "id": obj.get("id", ""),
                    "name": (obj.get("caption") or "").strip(),
                    "entity_type": SCHEMA_MAP.get(schema, "organization"),
                    "aliases": aliases,
                    "datasets": datasets,
                    "countries": countries,
                    "properties": props,
                    "updated_at": "now()",
                }

                if not record["id"] or not record["name"]:
                    total_skipped += 1
                    continue

                batch.append(record)

                if len(batch) >= BATCH_SIZE:
                    await self._upsert_batch(batch)
                    total_processed += len(batch)
                    logger.info("Upserted %d records…", total_processed)
                    batch = []
                    # Yield control to avoid blocking
                    await asyncio.sleep(0)

        # Final batch
        if batch:
            await self._upsert_batch(batch)
            total_processed += len(batch)

        logger.info(
            "Sanctions upsert complete: %d processed, %d skipped",
            total_processed,
            total_skipped,
        )

    async def _upsert_batch(self, batch: list[dict]) -> None:
        """Upsert a batch of sanctions entity rows."""
        if not batch:
            return

        async with AsyncSessionLocal() as db:
            for record in batch:
                # Use raw SQL for now() in updated_at
                updated_at_val = record["updated_at"]
                row = {k: v for k, v in record.items() if k != "updated_at"}

                stmt = pg_insert(SanctionsEntity).values(
                    **row,
                    updated_at=func.now(),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": stmt.excluded.name,
                        "entity_type": stmt.excluded.entity_type,
                        "aliases": stmt.excluded.aliases,
                        "datasets": stmt.excluded.datasets,
                        "countries": stmt.excluded.countries,
                        "properties": stmt.excluded.properties,
                        "updated_at": func.now(),
                    },
                )
                await db.execute(stmt)
            await db.commit()

    # ── Matching ──────────────────────────────────────────────────────────────

    async def match_entity(
        self,
        name: str,
        threshold: float = 0.5,
        limit: int = 5,
    ) -> list[dict]:
        """Find sanctions entities matching name using trigram similarity.

        Also searches aliases for matches.
        """
        async with AsyncSessionLocal() as db:
            # Name similarity match
            name_rows = await db.execute(
                text("""
                    SELECT id, name, entity_type, datasets, countries, aliases,
                           similarity(name, :name) AS score,
                           'name' AS matched_on
                    FROM sanctions_entities
                    WHERE similarity(name, :name) > :threshold
                    ORDER BY similarity(name, :name) DESC
                    LIMIT :limit
                """),
                {"name": name, "threshold": threshold, "limit": limit},
            )
            results: list[dict] = [dict(r._mapping) for r in name_rows.fetchall()]

            # Alias match — find rows where any alias is similar to the name
            # We use unnest + similarity, capped at a reasonable number
            if len(results) < limit:
                alias_rows = await db.execute(
                    text("""
                        SELECT DISTINCT ON (se.id)
                            se.id, se.name, se.entity_type, se.datasets, se.countries,
                            se.aliases,
                            similarity(alias_val, :name) AS score,
                            'alias' AS matched_on
                        FROM sanctions_entities se
                        CROSS JOIN LATERAL unnest(se.aliases) AS alias_val
                        WHERE similarity(alias_val, :name) > :threshold
                          AND se.id NOT IN (
                              SELECT id FROM sanctions_entities
                              WHERE similarity(name, :name) > :threshold
                          )
                        ORDER BY se.id, similarity(alias_val, :name) DESC
                        LIMIT :limit
                    """),
                    {"name": name, "threshold": threshold, "limit": limit},
                )
                alias_results = [dict(r._mapping) for r in alias_rows.fetchall()]
                results.extend(alias_results)

        # Sort combined results by score and de-dup by id
        seen: set[str] = set()
        final: list[dict] = []
        for r in sorted(results, key=lambda x: x["score"], reverse=True):
            if r["id"] not in seen:
                seen.add(r["id"])
                final.append(r)
                if len(final) >= limit:
                    break

        return final

    async def check_entity(
        self,
        entity_id: UUID,
        entity_name: str,
        entity_type: str,
    ) -> list[dict]:
        """Check a platform entity against sanctions lists and store any matches."""
        try:
            matches = await self.match_entity(entity_name, threshold=0.5, limit=10)
        except Exception as exc:
            logger.warning("Sanctions check failed for %s: %s", entity_name, exc)
            return []

        stored: list[dict] = []
        async with AsyncSessionLocal() as db:
            for match in matches:
                score: float = float(match["score"])
                if score < 0.7:
                    continue  # Only store meaningful matches

                # Check for existing match
                existing = await db.execute(
                    select(EntitySanctionsMatch).where(
                        EntitySanctionsMatch.entity_id == entity_id,
                        EntitySanctionsMatch.sanctions_entity_id == match["id"],
                    )
                )
                existing_match = existing.scalars().first()

                if existing_match:
                    # Update confidence if higher
                    if score > existing_match.confidence:
                        existing_match.confidence = score
                        existing_match.matched_on = match.get("matched_on", "name")
                    stored.append(match)
                else:
                    new_match = EntitySanctionsMatch(
                        entity_id=entity_id,
                        sanctions_entity_id=match["id"],
                        confidence=score,
                        matched_on=match.get("matched_on", "name"),
                        datasets=match.get("datasets") or [],
                    )
                    db.add(new_match)
                    stored.append(match)

            await db.commit()

        if stored:
            logger.info(
                "Entity '%s' has %d sanctions match(es)", entity_name, len(stored)
            )
        return stored

    async def get_entity_matches(self, entity_id: UUID) -> list[dict]:
        """Return stored sanctions matches for a platform entity."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(EntitySanctionsMatch, SanctionsEntity)
                .join(
                    SanctionsEntity,
                    EntitySanctionsMatch.sanctions_entity_id == SanctionsEntity.id,
                )
                .where(EntitySanctionsMatch.entity_id == entity_id)
                .order_by(EntitySanctionsMatch.confidence.desc())
            )
            rows = result.fetchall()

        matches = []
        for esm, se in rows:
            matches.append({
                "match_id": str(esm.id),
                "entity_id": str(esm.entity_id),
                "sanctions_entity_id": se.id,
                "sanctions_entity_name": se.name,
                "entity_type": se.entity_type,
                "confidence": esm.confidence,
                "matched_on": esm.matched_on,
                "datasets": esm.datasets or [],
                "countries": se.countries or [],
                "aliases": se.aliases or [],
                "created_at": esm.created_at.isoformat(),
                "opensanctions_url": f"https://opensanctions.org/entities/{se.id}/",
            })

        return matches

    async def search_sanctions(
        self,
        query: str,
        limit: int = 20,
        threshold: float = 0.3,
    ) -> list[dict]:
        """Search the sanctions database directly by name."""
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                text("""
                    SELECT id, name, entity_type, datasets, countries, aliases,
                           similarity(name, :q) AS score
                    FROM sanctions_entities
                    WHERE similarity(name, :q) > :threshold
                       OR name ILIKE :ilike
                    ORDER BY similarity(name, :q) DESC
                    LIMIT :limit
                """),
                {"q": query, "threshold": threshold, "ilike": f"%{query}%", "limit": limit},
            )
            return [dict(r._mapping) for r in rows.fetchall()]


# Singleton
sanctions_service = SanctionsService()
