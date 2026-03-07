"""Evidence linker — cross-reference narrative claims against hard data sources.

Checks each Claim against:
  - NASA FIRMS thermal anomalies (posts with source_type='firms')
  - ACLED conflict events (posts with source_type='acled')
  - Flight tracking anomalies (posts with source_type='flight')
  - Maritime AIS data (maritime_events table)
  - OSINT corroboration (entity overlap across social posts)

For spatially-aware evidence sources the Haversine formula is used with a
50 km radius. Temporal windows are ±6 h for hard sensors, ±12 h for OSINT.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from math import atan2, cos, radians, sin, sqrt
from typing import Optional

from sqlalchemy import func, or_, select

from app.db import AsyncSessionLocal
from app.models.narrative import Claim, ClaimEvidence
from app.models.post import Post

logger = logging.getLogger("orthanc.evidence")


class EvidenceLinker:
    """Cross-reference narrative claims against FIRMS, ACLED, flights, ships, OSINT."""

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    async def check_claim(self, claim: Claim) -> list[dict]:
        """Check a claim against all available evidence sources.

        Returns a list of evidence dicts ready for insertion into ClaimEvidence.
        Each dict has: evidence_type, evidence_source, supports, confidence, data
        """
        evidence: list[dict] = []

        if claim.location_lat is not None and claim.location_lng is not None:
            firms = await self._check_firms(
                claim.location_lat, claim.location_lng, claim.first_claimed_at
            )
            if firms:
                evidence.append(firms)

            acled = await self._check_acled(
                claim.location_lat, claim.location_lng, claim.first_claimed_at
            )
            if acled:
                evidence.append(acled)

            flights = await self._check_flights(
                claim.location_lat, claim.location_lng, claim.first_claimed_at
            )
            if flights:
                evidence.append(flights)

            maritime = await self._check_maritime(
                claim.location_lat, claim.location_lng, claim.first_claimed_at
            )
            if maritime:
                evidence.append(maritime)

        # Entity-based OSINT corroboration (no location required)
        osint = await self._check_osint_corroboration(claim)
        if osint:
            evidence.append(osint)

        return evidence

    async def persist_evidence(self, claim: Claim, evidence_list: list[dict]) -> None:
        """Write evidence records to DB and update claim counts/status."""
        if not evidence_list:
            return

        async with AsyncSessionLocal() as session:
            now = datetime.now(tz=timezone.utc)
            for ev in evidence_list:
                record = ClaimEvidence(
                    claim_id=claim.id,
                    evidence_type=ev.get("evidence_type"),
                    evidence_source=ev.get("evidence_source"),
                    evidence_data=ev.get("data"),
                    supports=ev.get("supports", True),
                    confidence=ev.get("confidence", 0.5),
                    detected_at=now,
                )
                session.add(record)

            # Refresh claim's evidence_count and status
            claim_row = await session.get(Claim, claim.id)
            if claim_row:
                claim_row.evidence_count = (claim_row.evidence_count or 0) + len(evidence_list)
                avg_confidence = sum(e.get("confidence", 0.5) for e in evidence_list) / len(evidence_list)
                if avg_confidence >= 0.7:
                    claim_row.status = "corroborated"
                elif avg_confidence >= 0.4:
                    claim_row.status = "partial"
                # else leave as 'unverified'
                session.add(claim_row)

            await session.commit()

    # ──────────────────────────────────────────────
    # Evidence sources
    # ──────────────────────────────────────────────

    async def _check_firms(
        self, lat: float, lng: float, claim_time: Optional[datetime]
    ) -> Optional[dict]:
        """Check NASA FIRMS for thermal anomalies within 50 km and ±6 h of claim."""
        if not claim_time:
            return None

        window_start = claim_time - timedelta(hours=6)
        window_end = claim_time + timedelta(hours=6)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Post).where(
                    Post.source_type == "firms",
                    Post.timestamp.between(window_start, window_end),
                )
            )
            firms_posts = result.scalars().all()

        best: Optional[dict] = None
        best_dist = float("inf")

        for post in firms_posts:
            # Lat/lng stored in raw_json by the FIRMS collector
            rj = post.raw_json or {}
            p_lat = rj.get("lat")
            p_lng = rj.get("lng")
            if p_lat is None or p_lng is None:
                continue
            try:
                dist = self._haversine_km(lat, lng, float(p_lat), float(p_lng))
            except (TypeError, ValueError):
                continue
            if dist < 50 and dist < best_dist:
                best_dist = dist
                best = {
                    "evidence_type": "firms",
                    "evidence_source": "NASA FIRMS",
                    "supports": True,
                    "confidence": round(max(0.3, 1.0 - dist / 50), 3),
                    "data": {
                        "post_id": str(post.id),
                        "distance_km": round(dist, 1),
                        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    },
                }

        return best

    async def _check_acled(
        self, lat: float, lng: float, claim_time: Optional[datetime]
    ) -> Optional[dict]:
        """Check ACLED conflict events within 50 km and ±12 h of claim."""
        if not claim_time:
            return None

        window_start = claim_time - timedelta(hours=12)
        window_end = claim_time + timedelta(hours=12)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Post).where(
                    Post.source_type == "acled",
                    Post.timestamp.between(window_start, window_end),
                )
            )
            posts = result.scalars().all()

        best: Optional[dict] = None
        best_dist = float("inf")

        for post in posts:
            rj = post.raw_json or {}
            p_lat = rj.get("latitude") or rj.get("lat")
            p_lng = rj.get("longitude") or rj.get("lng")
            if p_lat is None or p_lng is None:
                continue
            try:
                dist = self._haversine_km(lat, lng, float(p_lat), float(p_lng))
            except (TypeError, ValueError):
                continue
            if dist < 50 and dist < best_dist:
                best_dist = dist
                event_type = rj.get("event_type", "conflict event")
                best = {
                    "evidence_type": "acled",
                    "evidence_source": "ACLED",
                    "supports": True,
                    "confidence": round(max(0.3, 1.0 - dist / 50), 3),
                    "data": {
                        "post_id": str(post.id),
                        "distance_km": round(dist, 1),
                        "event_type": event_type,
                        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    },
                }

        return best

    async def _check_flights(
        self, lat: float, lng: float, claim_time: Optional[datetime]
    ) -> Optional[dict]:
        """Check flight tracking data within 100 km and ±3 h of claim."""
        if not claim_time:
            return None

        window_start = claim_time - timedelta(hours=3)
        window_end = claim_time + timedelta(hours=3)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Post).where(
                    Post.source_type == "flight",
                    Post.timestamp.between(window_start, window_end),
                )
            )
            posts = result.scalars().all()

        best: Optional[dict] = None
        best_dist = float("inf")

        for post in posts:
            rj = post.raw_json or {}
            p_lat = rj.get("lat") or rj.get("latitude")
            p_lng = rj.get("lng") or rj.get("longitude")
            if p_lat is None or p_lng is None:
                continue
            try:
                dist = self._haversine_km(lat, lng, float(p_lat), float(p_lng))
            except (TypeError, ValueError):
                continue
            if dist < 100 and dist < best_dist:
                best_dist = dist
                callsign = rj.get("callsign", "unknown")
                best = {
                    "evidence_type": "flight",
                    "evidence_source": "Flight Tracking",
                    "supports": True,
                    "confidence": round(max(0.2, 1.0 - dist / 100), 3),
                    "data": {
                        "post_id": str(post.id),
                        "distance_km": round(dist, 1),
                        "callsign": callsign,
                        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    },
                }

        return best

    async def _check_maritime(
        self, lat: float, lng: float, claim_time: Optional[datetime]
    ) -> Optional[dict]:
        """Check AIS/maritime data within 50 km and ±6 h of claim."""
        if not claim_time:
            return None

        window_start = claim_time - timedelta(hours=6)
        window_end = claim_time + timedelta(hours=6)

        async with AsyncSessionLocal() as session:
            # Check AIS posts (source_type='ais') stored via the AIS collector
            result = await session.execute(
                select(Post).where(
                    Post.source_type.in_(["ais", "maritime"]),
                    Post.timestamp.between(window_start, window_end),
                )
            )
            posts = result.scalars().all()

        best: Optional[dict] = None
        best_dist = float("inf")

        for post in posts:
            rj = post.raw_json or {}
            p_lat = rj.get("lat") or rj.get("latitude")
            p_lng = rj.get("lng") or rj.get("longitude")
            if p_lat is None or p_lng is None:
                continue
            try:
                dist = self._haversine_km(lat, lng, float(p_lat), float(p_lng))
            except (TypeError, ValueError):
                continue
            if dist < 50 and dist < best_dist:
                best_dist = dist
                vessel = rj.get("vessel_name") or rj.get("mmsi", "unknown vessel")
                best = {
                    "evidence_type": "maritime",
                    "evidence_source": "AIS / Maritime Tracking",
                    "supports": True,
                    "confidence": round(max(0.3, 1.0 - dist / 50), 3),
                    "data": {
                        "post_id": str(post.id),
                        "distance_km": round(dist, 1),
                        "vessel": vessel,
                        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    },
                }

        return best

    async def _check_osint_corroboration(self, claim: Claim) -> Optional[dict]:
        """Check if 3+ independent OSINT posts corroborate this claim via entity overlap."""
        if not claim.entity_names:
            return None

        base_time = claim.first_claimed_at or claim.created_at
        if not base_time:
            return None

        # Make timezone-aware if needed
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)

        window_start = base_time - timedelta(hours=12)
        window_end = base_time + timedelta(hours=12)

        # Use only first 3 entities to avoid absurdly long queries
        entity_subset = [e for e in (claim.entity_names or []) if e][:3]
        if not entity_subset:
            return None

        async with AsyncSessionLocal() as session:
            conditions = [Post.content.ilike(f"%{name}%") for name in entity_subset]
            result = await session.execute(
                select(func.count())
                .select_from(Post)
                .where(
                    or_(*conditions),
                    Post.timestamp.between(window_start, window_end),
                    Post.source_type.in_(["x", "telegram", "bluesky", "mastodon", "reddit"]),
                )
            )
            count = result.scalar() or 0

        if count >= 3:
            return {
                "evidence_type": "osint_corroboration",
                "evidence_source": "Multi-source OSINT",
                "supports": True,
                "confidence": round(min(0.9, count * 0.15), 3),
                "data": {
                    "corroborating_posts": count,
                    "entities_matched": entity_subset,
                },
            }

        return None

    # ──────────────────────────────────────────────
    # Maths
    # ──────────────────────────────────────────────

    @staticmethod
    def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Great-circle distance in kilometres."""
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlng = radians(lng2 - lng1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

evidence_linker = EvidenceLinker()
