"""Track LLM usage and costs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.llm_usage import LLMUsage

logger = logging.getLogger("orthanc.model_router")


class LLMUsageService:
    """Service for logging and querying LLM API usage."""

    def __init__(self, db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = db_session_factory

    async def log_usage(
        self,
        provider: str,
        model: str,
        task: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        cost_usd: Optional[float] = None,
        user_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log an LLM API call to the database."""
        user_uuid: Optional[UUID] = None
        if user_id:
            try:
                user_uuid = UUID(user_id)
            except (ValueError, AttributeError):
                logger.warning("Invalid user_id for LLM usage log: %s", user_id)

        entry = LLMUsage(
            provider=provider,
            model=model,
            task=task,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            user_id=user_uuid,
            error=error,
        )
        try:
            async with self._session_factory() as session:
                session.add(entry)
                await session.commit()
        except Exception as exc:
            logger.error("Failed to log LLM usage: %s", exc)

    async def get_usage_summary(self, hours: int = 24) -> dict:
        """Get usage summary: total calls, tokens, cost by task and model."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        async with self._session_factory() as session:
            # Overall totals
            totals_result = await session.execute(
                select(
                    func.count(LLMUsage.id).label("total_calls"),
                    func.sum(LLMUsage.tokens_in).label("total_tokens_in"),
                    func.sum(LLMUsage.tokens_out).label("total_tokens_out"),
                    func.sum(LLMUsage.cost_usd).label("total_cost_usd"),
                    func.avg(LLMUsage.latency_ms).label("avg_latency_ms"),
                ).where(LLMUsage.timestamp >= since)
            )
            totals = totals_result.one()

            # By task
            by_task_result = await session.execute(
                select(
                    LLMUsage.task,
                    func.count(LLMUsage.id).label("calls"),
                    func.sum(LLMUsage.tokens_in).label("tokens_in"),
                    func.sum(LLMUsage.tokens_out).label("tokens_out"),
                    func.sum(LLMUsage.cost_usd).label("cost_usd"),
                )
                .where(LLMUsage.timestamp >= since)
                .group_by(LLMUsage.task)
                .order_by(func.count(LLMUsage.id).desc())
            )
            by_task = [
                {
                    "task": row.task,
                    "calls": row.calls,
                    "tokens_in": row.tokens_in or 0,
                    "tokens_out": row.tokens_out or 0,
                    "cost_usd": float(row.cost_usd) if row.cost_usd else None,
                }
                for row in by_task_result
            ]

            # By model
            by_model_result = await session.execute(
                select(
                    LLMUsage.model,
                    LLMUsage.provider,
                    func.count(LLMUsage.id).label("calls"),
                    func.sum(LLMUsage.tokens_in).label("tokens_in"),
                    func.sum(LLMUsage.tokens_out).label("tokens_out"),
                    func.sum(LLMUsage.cost_usd).label("cost_usd"),
                )
                .where(LLMUsage.timestamp >= since)
                .group_by(LLMUsage.model, LLMUsage.provider)
                .order_by(func.count(LLMUsage.id).desc())
            )
            by_model = [
                {
                    "model": row.model,
                    "provider": row.provider,
                    "calls": row.calls,
                    "tokens_in": row.tokens_in or 0,
                    "tokens_out": row.tokens_out or 0,
                    "cost_usd": float(row.cost_usd) if row.cost_usd else None,
                }
                for row in by_model_result
            ]

        return {
            "period_hours": hours,
            "since": since.isoformat(),
            "total_calls": totals.total_calls or 0,
            "total_tokens_in": int(totals.total_tokens_in or 0),
            "total_tokens_out": int(totals.total_tokens_out or 0),
            "total_cost_usd": float(totals.total_cost_usd) if totals.total_cost_usd else None,
            "avg_latency_ms": float(totals.avg_latency_ms) if totals.avg_latency_ms else None,
            "by_task": by_task,
            "by_model": by_model,
        }

    async def get_daily_usage(self, days: int = 7) -> list[dict]:
        """Daily usage breakdown."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.date_trunc("day", LLMUsage.timestamp).label("day"),
                    func.count(LLMUsage.id).label("calls"),
                    func.sum(LLMUsage.tokens_in).label("tokens_in"),
                    func.sum(LLMUsage.tokens_out).label("tokens_out"),
                    func.sum(LLMUsage.cost_usd).label("cost_usd"),
                )
                .where(LLMUsage.timestamp >= since)
                .group_by(text("1"))
                .order_by(text("1"))
            )
            return [
                {
                    "day": row.day.date().isoformat() if row.day else None,
                    "calls": row.calls,
                    "tokens_in": row.tokens_in or 0,
                    "tokens_out": row.tokens_out or 0,
                    "cost_usd": float(row.cost_usd) if row.cost_usd else None,
                }
                for row in result
            ]
