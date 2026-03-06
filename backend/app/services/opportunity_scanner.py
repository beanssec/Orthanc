"""Opportunity Scanner — analyses OSINT entity trends and generates financial signals via AI."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, text

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.financial import Holding, Quote, Signal
from app.services.ai_models import get_model, AI_MODELS
from app.services.collector_manager import collector_manager
from app.services.entity_ticker_service import entity_ticker_service

logger = logging.getLogger("orthanc.services.opportunity_scanner")

DEFAULT_MODEL = "grok-3-mini"

SYSTEM_PROMPT = (
    "You are a financial intelligence analyst. Based on the OSINT data and entity trends "
    "provided, generate actionable financial signals.\n\n"
    "For each signal, provide:\n"
    "1. signal_type: 'opportunity', 'risk', or 'impact'\n"
    "2. severity: 'low', 'medium', 'high', or 'critical'\n"
    "3. title: one-line description\n"
    "4. summary: 2-3 sentences explaining the signal and rationale\n"
    "5. affected_tickers: JSON array of ticker strings\n"
    "6. timeframe: 'immediate', '24h', or '1 week'\n"
    "7. portfolio_impact: 'positive', 'negative', or 'neutral'\n\n"
    "Return ONLY a JSON array of signal objects. Be analytical and evidence-based. "
    "Focus on actionable intelligence, not speculation."
)


class OpportunityScanner:
    """Analyses OSINT data for financial signals and opportunities."""

    async def scan(self, user_id: str, model_id: str | None = None) -> list[dict]:
        """
        Run a full opportunity scan:
        1. Get spiking entities (>2x spike in last 6h vs 7d average)
        2. Map spiking entities to tickers
        3. Check portfolio overlap
        4. Get current market data for affected tickers
        5. Call AI to generate structured signals
        6. Save signals to DB
        7. Return signals
        """
        model_id = model_id or DEFAULT_MODEL
        model_config = get_model(model_id)
        if not model_config:
            logger.warning("OpportunityScanner: unknown model %s", model_id)
            model_config = get_model(DEFAULT_MODEL)

        # Get user AI credentials
        cred_provider = model_config["credential_provider"]  # type: ignore[index]
        key_field = model_config["key_field"]  # type: ignore[index]
        endpoint = model_config["endpoint"]  # type: ignore[index]
        model_name = model_config["id"]  # type: ignore[index]

        keys = await collector_manager.get_keys(user_id, cred_provider)
        api_key = (keys or {}).get(key_field, "")
        if not api_key:
            # Try xAI as fallback
            fallback_keys = await collector_manager.get_keys(user_id, "x")
            api_key = (fallback_keys or {}).get("api_key", "")
            if api_key:
                endpoint = "https://api.x.ai/v1/chat/completions"
                model_name = "grok-3-mini"
                cred_provider = "x"

        # --- Step 1: Find spiking entities ---
        spiking_entities = await self._get_spiking_entities()
        if not spiking_entities:
            logger.info("OpportunityScanner: no spiking entities found for user %s", user_id)
            return []

        logger.info(
            "OpportunityScanner: %d spiking entities for user %s: %s",
            len(spiking_entities),
            user_id,
            [e["name"] for e in spiking_entities[:10]],
        )

        # --- Step 2: Map to tickers ---
        entity_names = [e["name"] for e in spiking_entities]
        ticker_mappings = await entity_ticker_service.get_tickers_for_entities(entity_names)

        if not ticker_mappings:
            logger.info("OpportunityScanner: no ticker mappings found for spiking entities")
            # Still run scan with just entity data — AI may still generate insights
            affected_tickers_info: list[dict] = []
        else:
            affected_tickers_info = ticker_mappings

        # --- Step 3: Get user's portfolio ---
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Holding).where(Holding.user_id == uuid.UUID(user_id))
            )
            holdings = result.scalars().all()

        portfolio_tickers = {h.ticker for h in holdings}
        portfolio_context = [
            {
                "ticker": h.ticker,
                "exchange": h.exchange,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
            }
            for h in holdings
        ]

        # --- Step 4: Get current quotes for affected tickers ---
        affected_ticker_names = list({m["ticker"] for m in affected_tickers_info})
        quotes_context: list[dict] = []
        if affected_ticker_names:
            async with AsyncSessionLocal() as session:
                for ticker in affected_ticker_names[:20]:  # limit to 20
                    result = await session.execute(
                        select(Quote)
                        .where(Quote.ticker == ticker)
                        .order_by(Quote.fetched_at.desc())
                        .limit(1)
                    )
                    q = result.scalar_one_or_none()
                    if q:
                        quotes_context.append(
                            {
                                "ticker": q.ticker,
                                "exchange": q.exchange,
                                "price": q.price,
                                "change_pct": q.change_pct,
                                "currency": q.currency,
                            }
                        )

        # --- Step 5: Build AI context ---
        context = self._build_context(
            spiking_entities, affected_tickers_info, quotes_context, portfolio_context
        )

        if not api_key:
            logger.warning(
                "OpportunityScanner: no AI API key for user %s — returning entity-only signals",
                user_id,
            )
            signals = self._fallback_signals(spiking_entities, ticker_mappings, user_id)
        else:
            signals = await self._call_ai(context, api_key, endpoint, model_name)

        if not signals:
            logger.info("OpportunityScanner: AI returned no signals for user %s", user_id)
            return []

        # --- Step 6: Save signals to DB ---
        saved: list[dict] = []
        # Build entity-name → spike_count lookup for per-signal attribution
        entity_spike_map = {e["name"].lower(): e.get("spike_count", 0) for e in spiking_entities}
        # Build ticker → [entity_names] lookup from mappings
        ticker_to_entities: dict[str, list[str]] = {}
        for m in affected_tickers_info:
            ticker_to_entities.setdefault(m["ticker"], []).append(m["entity_name"].lower())

        async with AsyncSessionLocal() as session:
            for s in signals:
                tickers_affected = s.get("affected_tickers", [])
                if isinstance(tickers_affected, list):
                    tickers_json = json.dumps(tickers_affected)
                else:
                    tickers_json = str(tickers_affected)

                # Calculate per-signal post count based on entities linked to this signal's tickers
                signal_ticker_set = set(tickers_affected) if isinstance(tickers_affected, list) else set()
                relevant_entities: set[str] = set()
                for t in signal_ticker_set:
                    for ename in ticker_to_entities.get(t, []):
                        relevant_entities.add(ename)

                if relevant_entities:
                    per_signal_count = sum(
                        entity_spike_map.get(en, 0) for en in relevant_entities
                    )
                else:
                    # No ticker mapping — attribute all spiking activity
                    per_signal_count = sum(e.get("spike_count", 0) for e in spiking_entities)

                trigger_names = [e["name"] for e in spiking_entities[:5]]
                signal = Signal(
                    user_id=uuid.UUID(user_id),
                    signal_type=s.get("signal_type", "impact"),
                    severity=s.get("severity", "medium"),
                    title=s.get("title", "Untitled signal"),
                    summary=s.get("summary", ""),
                    affected_tickers=tickers_json,
                    trigger_entities=json.dumps(trigger_names),
                    trigger_post_count=per_signal_count,
                    portfolio_impact=s.get("portfolio_impact", "neutral"),
                    generated_at=datetime.now(timezone.utc),
                )
                session.add(signal)
                await session.flush()
                saved.append(
                    {
                        "id": str(signal.id),
                        "signal_type": signal.signal_type,
                        "severity": signal.severity,
                        "title": signal.title,
                        "summary": signal.summary,
                        "affected_tickers": tickers_affected,
                        "trigger_entities": trigger_names,
                        "portfolio_impact": signal.portfolio_impact,
                        "generated_at": signal.generated_at.isoformat(),
                        "timeframe": s.get("timeframe", "24h"),
                    }
                )
            await session.commit()

        logger.info("OpportunityScanner: saved %d signals for user %s", len(saved), user_id)
        return saved

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _get_spiking_entities(self) -> list[dict]:
        """Find entities with >2x spike in last 6h vs 7d rolling average."""
        now = datetime.now(timezone.utc)
        cutoff_6h = now - timedelta(hours=6)
        cutoff_7d = now - timedelta(days=7)

        async with AsyncSessionLocal() as session:
            # Mentions in last 6h per entity
            result_6h = await session.execute(
                select(
                    Entity.id,
                    Entity.name,
                    Entity.type,
                    func.count(EntityMention.id).label("count_6h"),
                )
                .join(EntityMention, EntityMention.entity_id == Entity.id)
                .where(EntityMention.extracted_at >= cutoff_6h)
                .group_by(Entity.id, Entity.name, Entity.type)
            )
            rows_6h = result_6h.all()

            if not rows_6h:
                return []

            entity_ids = [row.id for row in rows_6h]

            # Historical average over 7d (per 6h window = 7*4 = 28 periods)
            result_7d = await session.execute(
                select(
                    Entity.id,
                    func.count(EntityMention.id).label("count_7d"),
                )
                .join(EntityMention, EntityMention.entity_id == Entity.id)
                .where(
                    EntityMention.extracted_at >= cutoff_7d,
                    EntityMention.extracted_at < cutoff_6h,
                    Entity.id.in_(entity_ids),
                )
                .group_by(Entity.id)
            )
            rows_7d = {row.id: row.count_7d for row in result_7d.all()}

        spiking = []
        for row in rows_6h:
            count_6h = row.count_6h
            # Average 6h rate over the past 7 days (27 periods)
            historical_total = rows_7d.get(row.id, 0)
            historical_per_6h = historical_total / 27.0 if historical_total > 0 else 0

            spike_ratio = count_6h / max(historical_per_6h, 0.5)  # avoid div/0

            if spike_ratio >= 2.0 and count_6h >= 2:
                spiking.append(
                    {
                        "id": str(row.id),
                        "name": row.name,
                        "type": row.type,
                        "spike_count": count_6h,
                        "historical_avg": round(historical_per_6h, 2),
                        "spike_ratio": round(spike_ratio, 2),
                    }
                )

        spiking.sort(key=lambda x: x["spike_ratio"], reverse=True)
        return spiking[:20]  # Top 20

    def _build_context(
        self,
        spiking: list[dict],
        mappings: list[dict],
        quotes: list[dict],
        portfolio: list[dict],
    ) -> str:
        lines = [
            "=== SPIKING ENTITIES (last 6h vs 7d average) ===",
        ]
        for e in spiking[:15]:
            lines.append(
                f"  {e['name']} ({e['type']}): {e['spike_count']} mentions "
                f"(spike ratio: {e['spike_ratio']}x)"
            )

        lines.append("\n=== AFFECTED FINANCIAL INSTRUMENTS ===")
        for m in mappings[:15]:
            lines.append(
                f"  {m['entity_name']} → {m['ticker']} ({m['exchange']}) "
                f"[{m['relationship']}, confidence={m['confidence']}]"
            )

        lines.append("\n=== CURRENT MARKET DATA ===")
        if quotes:
            for q in quotes:
                chg = f"{q['change_pct']:+.2f}%" if q.get("change_pct") is not None else "N/A"
                lines.append(
                    f"  {q['ticker']} ({q['exchange']}): "
                    f"{q.get('currency','')} {q.get('price', 'N/A')} ({chg})"
                )
        else:
            lines.append("  No current quotes available")

        lines.append("\n=== USER PORTFOLIO ===")
        if portfolio:
            for h in portfolio:
                lines.append(
                    f"  {h['ticker']} ({h['exchange']}): "
                    f"{h['quantity']} units @ avg {h['avg_cost']}"
                )
        else:
            lines.append("  No portfolio holdings")

        return "\n".join(lines)

    async def _call_ai(
        self,
        context: str,
        api_key: str,
        endpoint: str,
        model_id: str,
    ) -> list[dict]:
        """Call the AI model to generate financial signals."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter" in endpoint:
            headers["HTTP-Referer"] = "https://orthanc.local"
            headers["X-Title"] = "Orthanc OSINT"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    endpoint,
                    json={
                        "model": model_id,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    "Analyse this OSINT intelligence data and generate "
                                    f"financial signals:\n\n{context}"
                                ),
                            },
                        ],
                        "temperature": 0.2,
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
        except Exception:
            logger.exception("OpportunityScanner: AI call failed")
            return []

        # Strip markdown fences
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()

        try:
            signals = json.loads(raw)
            if isinstance(signals, list):
                return signals
            logger.warning("OpportunityScanner: AI returned non-list: %s", type(signals))
        except json.JSONDecodeError as e:
            logger.warning("OpportunityScanner: JSON parse error: %s — raw: %s", e, raw[:200])

        return []

    def _fallback_signals(
        self,
        spiking: list[dict],
        mappings: list[dict],
        user_id: str,
    ) -> list[dict]:
        """Generate basic signals without AI when no API key is configured."""
        signals = []
        for mapping in mappings[:5]:
            entity = next(
                (e for e in spiking if e["name"].lower() == mapping["entity_name"].lower()),
                spiking[0] if spiking else {},
            )
            if not entity:
                continue
            signals.append(
                {
                    "signal_type": "impact",
                    "severity": "medium" if entity.get("spike_ratio", 1) < 5 else "high",
                    "title": f"{entity['name']} activity spike may affect {mapping['ticker']}",
                    "summary": (
                        f"{entity['name']} has seen a {entity.get('spike_ratio', 1):.1f}x spike "
                        f"in mentions ({entity.get('spike_count', 0)} mentions in last 6h). "
                        f"This entity has a {mapping['relationship']} relationship with "
                        f"{mapping['ticker']} ({mapping['exchange']})."
                    ),
                    "affected_tickers": [mapping["ticker"]],
                    "portfolio_impact": "neutral",
                    "timeframe": "24h",
                }
            )
        return signals


opportunity_scanner = OpportunityScanner()
