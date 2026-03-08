"""Co-occurrence engine — builds entity relationship graph from post co-mentions."""
from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime, timezone, timedelta
from itertools import combinations
from typing import Optional

from sqlalchemy import select, text, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.entity_relationship import EntityRelationship

logger = logging.getLogger("orthanc.cooccurrence")

_LOOP_INTERVAL_SECONDS = 30 * 60  # 30 minutes
_MAX_POSTS_PER_RUN = 1000
_MAX_SAMPLE_POST_IDS = 10


class CooccurrenceService:
    """Builds and serves the entity co-occurrence graph."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._last_run: datetime | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background co-occurrence computation task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._compute_loop())
            logger.info("Co-occurrence service started")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Background loop ───────────────────────────────────────────────────────

    async def _compute_loop(self) -> None:
        """Run co-occurrence computation every 30 minutes."""
        while True:
            try:
                await self.compute_cooccurrences()
            except Exception as exc:
                logger.error("Co-occurrence computation failed: %s", exc, exc_info=True)
            await asyncio.sleep(_LOOP_INTERVAL_SECONDS)

    # ── Core computation ──────────────────────────────────────────────────────

    async def compute_cooccurrences(self) -> None:
        """Process posts and build pairwise entity co-occurrence relationships.

        On first run processes up to the last 1000 posts.
        On subsequent runs only processes posts since last run.
        """
        async with AsyncSessionLocal() as db:
            # Determine time window
            if self._last_run is None:
                # First run — process all recent posts (limit 1000)
                since = None
            else:
                since = self._last_run

            # Build query: get distinct post_ids that have entity mentions
            # For each post, fetch all entity_ids mentioned
            if since:
                stmt = (
                    select(EntityMention.post_id, EntityMention.entity_id)
                    .where(EntityMention.extracted_at >= since)
                    .order_by(EntityMention.post_id)
                )
            else:
                # Subquery: get latest 1000 post_ids with mentions
                subq = (
                    select(EntityMention.post_id)
                    .distinct()
                    .order_by(EntityMention.post_id.desc())
                    .limit(_MAX_POSTS_PER_RUN)
                    .subquery()
                )
                stmt = (
                    select(EntityMention.post_id, EntityMention.entity_id)
                    .where(EntityMention.post_id.in_(select(subq)))
                )

            result = await db.execute(stmt)
            rows = result.all()

        if not rows:
            logger.debug("Co-occurrence: no new mentions to process")
            self._last_run = datetime.now(tz=timezone.utc)
            return

        # Group entity_ids by post_id
        post_entities: dict[uuid.UUID, list[uuid.UUID]] = {}
        for post_id, entity_id in rows:
            post_entities.setdefault(post_id, []).append(entity_id)

        # Build pairwise co-occurrences
        # pair -> {weight: int, post_ids: list[str]}
        pair_data: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}

        for post_id, entity_ids in post_entities.items():
            # Deduplicate entity_ids within this post
            unique_entities = list(set(entity_ids))
            if len(unique_entities) < 2:
                continue

            for a_id, b_id in combinations(sorted(unique_entities, key=str), 2):
                # Always store with a < b to keep canonical order
                key = (a_id, b_id)
                if key not in pair_data:
                    pair_data[key] = {"weight": 0, "post_ids": []}
                pair_data[key]["weight"] += 1
                if len(pair_data[key]["post_ids"]) < _MAX_SAMPLE_POST_IDS:
                    pair_data[key]["post_ids"].append(str(post_id))

        if not pair_data:
            logger.debug("Co-occurrence: no pairs found in processed posts")
            self._last_run = datetime.now(tz=timezone.utc)
            return

        logger.info("Co-occurrence: upserting %d entity pairs", len(pair_data))
        now = datetime.now(tz=timezone.utc)

        async with AsyncSessionLocal() as db:
            for (a_id, b_id), data in pair_data.items():
                # Try to fetch existing relationship
                existing_stmt = select(EntityRelationship).where(
                    EntityRelationship.entity_a_id == a_id,
                    EntityRelationship.entity_b_id == b_id,
                )
                existing_result = await db.execute(existing_stmt)
                rel = existing_result.scalars().first()

                if rel is not None:
                    rel.weight += data["weight"]
                    rel.last_seen = now
                    # Merge sample post IDs (keep max 10)
                    existing_samples = rel.sample_post_ids or []
                    new_samples = data["post_ids"]
                    combined = list(dict.fromkeys(existing_samples + new_samples))
                    rel.sample_post_ids = combined[:_MAX_SAMPLE_POST_IDS]
                else:
                    rel = EntityRelationship(
                        entity_a_id=a_id,
                        entity_b_id=b_id,
                        weight=data["weight"],
                        first_seen=now,
                        last_seen=now,
                        sample_post_ids=data["post_ids"][:_MAX_SAMPLE_POST_IDS],
                    )
                    db.add(rel)

            await db.commit()

        self._last_run = now
        logger.info("Co-occurrence: computation complete (%d pairs processed)", len(pair_data))

    # ── Graph queries ─────────────────────────────────────────────────────────

    async def get_graph(
        self,
        min_weight: int = 3,
        limit: int = 200,
        entity_type: Optional[str] = None,
        center_entity_id: Optional[str] = None,
    ) -> dict:
        """Get the co-occurrence graph as nodes + edges.

        Returns:
            {
                "nodes": [{"id": str, "name": str, "type": str, "mentions": int, "size": float}],
                "edges": [{"source": str, "target": str, "weight": int}]
            }
        """
        async with AsyncSessionLocal() as db:
            # Get top edges by weight
            edge_query = (
                select(EntityRelationship)
                .where(EntityRelationship.weight >= min_weight)
                .order_by(EntityRelationship.weight.desc())
                .limit(limit)
            )

            if center_entity_id:
                center_uuid = uuid.UUID(center_entity_id)
                edge_query = edge_query.where(
                    or_(
                        EntityRelationship.entity_a_id == center_uuid,
                        EntityRelationship.entity_b_id == center_uuid,
                    )
                )

            edges_result = await db.execute(edge_query)
            relationships = edges_result.scalars().all()

            if not relationships:
                return {"nodes": [], "edges": []}

            # Collect all entity IDs referenced in edges
            entity_ids: set[uuid.UUID] = set()
            for rel in relationships:
                entity_ids.add(rel.entity_a_id)
                entity_ids.add(rel.entity_b_id)

            # Fetch entity details
            entity_query = select(Entity).where(Entity.id.in_(entity_ids))
            if entity_type:
                entity_query = entity_query.where(Entity.type == entity_type)

            entities_result = await db.execute(entity_query)
            entities = {e.id: e for e in entities_result.scalars().all()}

            # Filter edges to only include entities that passed the type filter
            valid_entity_ids = set(entities.keys())

            # Build node list
            max_mentions = max((e.mention_count for e in entities.values()), default=1)
            nodes = []
            for eid, entity in entities.items():
                size = math.sqrt(entity.mention_count / max(max_mentions, 1)) * 30 + 6
                nodes.append({
                    "id": str(eid),
                    "name": entity.name,
                    "type": entity.type,
                    "mentions": entity.mention_count,
                    "size": round(size, 2),
                })

            # Build edge list (skip edges where either entity was filtered out)
            edges = []
            for rel in relationships:
                if rel.entity_a_id in valid_entity_ids and rel.entity_b_id in valid_entity_ids:
                    edges.append({
                        "source": str(rel.entity_a_id),
                        "target": str(rel.entity_b_id),
                        "weight": rel.weight,
                    })

            return {"nodes": nodes, "edges": edges}

    async def get_entity_neighbors(self, entity_id: str, limit: int = 20) -> dict:
        """Get entities most closely related to a specific entity.

        Returns same {nodes, edges} format centered on the given entity.
        """
        async with AsyncSessionLocal() as db:
            center_uuid = uuid.UUID(entity_id)

            # Get center entity
            center_result = await db.execute(
                select(Entity).where(Entity.id == center_uuid)
            )
            center_entity = center_result.scalars().first()
            if not center_entity:
                return {"nodes": [], "edges": []}

            # Get top relationships involving this entity
            rel_query = (
                select(EntityRelationship)
                .where(
                    or_(
                        EntityRelationship.entity_a_id == center_uuid,
                        EntityRelationship.entity_b_id == center_uuid,
                    )
                )
                .order_by(EntityRelationship.weight.desc())
                .limit(limit)
            )
            rels_result = await db.execute(rel_query)
            relationships = rels_result.scalars().all()

            # Collect neighbor entity IDs
            neighbor_ids: set[uuid.UUID] = set()
            for rel in relationships:
                neighbor_ids.add(rel.entity_a_id)
                neighbor_ids.add(rel.entity_b_id)
            neighbor_ids.discard(center_uuid)

            # Fetch neighbor entities
            neighbors_result = await db.execute(
                select(Entity).where(Entity.id.in_(neighbor_ids))
            )
            entities = {e.id: e for e in neighbors_result.scalars().all()}
            entities[center_uuid] = center_entity

            # Build nodes
            max_mentions = max((e.mention_count for e in entities.values()), default=1)
            nodes = []
            for eid, entity in entities.items():
                size = math.sqrt(entity.mention_count / max(max_mentions, 1)) * 30 + 6
                nodes.append({
                    "id": str(eid),
                    "name": entity.name,
                    "type": entity.type,
                    "mentions": entity.mention_count,
                    "size": round(size, 2),
                })

            # Build edges
            valid_ids = set(entities.keys())
            edges = [
                {
                    "source": str(rel.entity_a_id),
                    "target": str(rel.entity_b_id),
                    "weight": rel.weight,
                }
                for rel in relationships
                if rel.entity_a_id in valid_ids and rel.entity_b_id in valid_ids
            ]

            return {"nodes": nodes, "edges": edges}


cooccurrence_service = CooccurrenceService()
