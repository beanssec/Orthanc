"""Entity-to-ticker mapping service.

Given a list of trending entity names, returns the financial tickers
they are likely to affect (based on the entity_ticker_map table).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models.financial import EntityTickerMap

logger = logging.getLogger("orthanc.services.entity_ticker")


class EntityTickerService:
    """Loads and queries entity → ticker mappings."""

    async def get_tickers_for_entities(
        self,
        entity_names: list[str],
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """
        Given a list of entity names, return all affected tickers.

        Returns a list of dicts: {ticker, exchange, relationship, confidence, entity_name}
        sorted by confidence descending.
        """
        if not entity_names:
            return []

        # Normalise for case-insensitive lookup
        lower_names = [n.lower() for n in entity_names]

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(EntityTickerMap))
            mappings = result.scalars().all()

        matched: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for m in mappings:
            if m.entity_name.lower() not in lower_names:
                continue
            if (m.confidence or 0) < min_confidence:
                continue
            key = (m.ticker, m.exchange or "")
            if key in seen:
                continue
            seen.add(key)
            matched.append(
                {
                    "ticker": m.ticker,
                    "exchange": m.exchange,
                    "relationship": m.relationship,
                    "confidence": m.confidence,
                    "entity_name": m.entity_name,
                    "entity_type": m.entity_type,
                }
            )

        matched.sort(key=lambda x: x["confidence"] or 0, reverse=True)
        return matched

    async def list_mappings(self, entity_name: Optional[str] = None) -> list[dict]:
        """List all entity-ticker mappings, optionally filtered by entity name."""
        async with AsyncSessionLocal() as session:
            stmt = select(EntityTickerMap)
            if entity_name:
                stmt = stmt.where(
                    EntityTickerMap.entity_name.ilike(f"%{entity_name}%")
                )
            result = await session.execute(stmt)
            mappings = result.scalars().all()

        return [
            {
                "id": str(m.id),
                "entity_name": m.entity_name,
                "entity_type": m.entity_type,
                "ticker": m.ticker,
                "exchange": m.exchange,
                "relationship": m.relationship,
                "confidence": m.confidence,
            }
            for m in mappings
        ]

    async def add_mapping(
        self,
        entity_name: str,
        entity_type: Optional[str],
        ticker: str,
        exchange: str,
        relationship: Optional[str],
        confidence: float,
    ) -> dict:
        """Add a new entity-ticker mapping."""
        mapping = EntityTickerMap(
            entity_name=entity_name,
            entity_type=entity_type,
            ticker=ticker,
            exchange=exchange,
            relationship=relationship,
            confidence=confidence,
        )
        async with AsyncSessionLocal() as session:
            session.add(mapping)
            await session.commit()
            await session.refresh(mapping)
        return {
            "id": str(mapping.id),
            "entity_name": mapping.entity_name,
            "ticker": mapping.ticker,
            "exchange": mapping.exchange,
        }

    async def delete_mapping(self, mapping_id: str) -> bool:
        """Delete an entity-ticker mapping by ID."""
        import uuid as _uuid
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EntityTickerMap).where(
                    EntityTickerMap.id == _uuid.UUID(mapping_id)
                )
            )
            mapping = result.scalar_one_or_none()
            if not mapping:
                return False
            await session.delete(mapping)
            await session.commit()
        return True


entity_ticker_service = EntityTickerService()
