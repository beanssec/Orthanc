"""AI intelligence brief generator — multi-model support.

Sprint tasks:
  TASK-73 — source reliability context in brief prompt
  TASK-74 — entity relationship (co-occurrence) context in brief prompt
  TASK-75 — structured JSON output format with fallback to raw text
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.models.brief import Brief
from app.services.ai_models import get_model, AI_MODELS, make_fallback_model_config, cache_live_models, fetch_live_openrouter_models
from app.services.model_router import model_router
from app.services.brief_confidence import compute_brief_confidence, confidence_context_block
from sqlalchemy import select, func, text

logger = logging.getLogger("orthanc.brief_generator")

# ── TASK-75: Structured output schema ─────────────────────────────────────────

BRIEF_JSON_SCHEMA = """{
  "executive_summary": "<comprehensive 4-6 sentence overview of the key intelligence picture, covering major theatres and themes>",
  "key_developments": ["<detailed development with specifics — who, what, where, when, sourcing>", "..."],
  "regional_breakdown": [
    {"region": "<region/theatre name>", "summary": "<2-3 sentence assessment of developments in this region>"}
  ],
  "entity_watch": [
    {"entity": "<name>", "role": "<current role/posture>", "note": "<detailed assessment of their significance, actions, and trajectory>"}
  ],
  "narrative_shifts": ["<detailed shift with context on what changed and why it matters>", "..."],
  "risks_and_outlook": ["<forward-looking risk or projection based on current intelligence>", "..."],
  "recommendations": ["<specific, actionable analyst recommendation with collection focus>", "..."]
}"""

SYSTEM_PROMPT = (
    "You are a senior OSINT intelligence analyst producing a comprehensive intelligence brief. "
    "Analyze ALL provided posts thoroughly — do not skip or summarize away important developments.\n\n"
    "Posts are tagged with their selection reason (ALERT, FUSION, NARRATIVE, TRENDING, TEMPORAL) "
    "indicating why they were flagged as significant. Weight ALERT and FUSION posts highest.\n\n"
    "Return ONLY a valid JSON object matching this schema (no markdown fences, no explanation):\n"
    f"{BRIEF_JSON_SCHEMA}\n\n"
    "Requirements:\n"
    "- executive_summary: 4-6 sentences covering all major themes\n"
    "- key_developments: 8-15 items with specific details (names, numbers, locations, dates)\n"
    "- regional_breakdown: group developments by geographic theatre (e.g., Middle East, Europe, Indo-Pacific)\n"
    "- entity_watch: 6-10 key actors with detailed assessments\n"
    "- narrative_shifts: identify how narratives are evolving, not just what happened\n"
    "- risks_and_outlook: forward-looking analysis based on observed patterns\n"
    "- recommendations: specific collection priorities and monitoring guidance\n\n"
    "Be thorough, analytical, and professional. Cite specifics from the source material. "
    "Avoid vague summaries — this brief should give a reader full situational awareness."
)

DEFAULT_MODEL = "grok-3-mini"

# ── TASK-73: Source reliability thresholds ─────────────────────────────────────

_HIGH_RELIABILITY_MIN = 0.65   # score >= this → high
_LOW_RELIABILITY_MAX = 0.35    # score <= this → low
_LOW_SOURCE_FRACTION_WARN = 0.5  # >50% low-reliability → warning


async def _compute_source_reliability_context(
    session,
    post_uuids: list[uuid.UUID],
) -> dict:
    """
    TASK-73: Count high/medium/low reliability sources among the brief's posts.
    Returns a dict with counts and a warning flag.
    Falls back to empty result if table absent.
    """
    try:
        from app.models.source_reliability import SourceReliability
        from app.models.source import Source

        # Get source_ids for these posts
        if not post_uuids:
            return {}

        post_result = await session.execute(
            select(Post.source_id).where(Post.id.in_(post_uuids)).distinct()
        )
        source_ids = [r[0] for r in post_result.all() if r[0]]

        if not source_ids:
            return {}

        rel_result = await session.execute(
            select(SourceReliability.reliability_score)
            .where(SourceReliability.source_id.in_(source_ids))
        )
        scores = [r[0] for r in rel_result.all() if r[0] is not None]

        if not scores:
            return {}

        high = sum(1 for s in scores if s >= _HIGH_RELIABILITY_MIN)
        low = sum(1 for s in scores if s <= _LOW_RELIABILITY_MAX)
        medium = len(scores) - high - low

        low_fraction = low / len(scores) if scores else 0.0
        primarily_low = low_fraction > _LOW_SOURCE_FRACTION_WARN

        return {
            "high": high,
            "medium": medium,
            "low": low,
            "total_rated": len(scores),
            "low_fraction": round(low_fraction, 2),
            "primarily_low": primarily_low,
        }
    except Exception as exc:
        logger.debug("source_reliability_context: failed (non-fatal): %s", exc)
        return {}


def _format_reliability_note(rel_ctx: dict) -> str:
    """Format a reliability note for inclusion in the brief prompt."""
    if not rel_ctx:
        return ""
    parts = [
        f"SOURCE RELIABILITY CONTEXT:",
        f"  High-reliability sources: {rel_ctx.get('high', 0)}",
        f"  Medium-reliability sources: {rel_ctx.get('medium', 0)}",
        f"  Low-reliability sources: {rel_ctx.get('low', 0)}",
    ]
    if rel_ctx.get("primarily_low"):
        parts.append(
            "  ⚠ WARNING: This brief is based primarily on low-reliability sources. "
            "Treat all claims with elevated scepticism."
        )
    return "\n".join(parts)


# ── TASK-74: Entity co-occurrence context ─────────────────────────────────────

async def _fetch_top_entity_pairs(
    session,
    post_uuids: list[uuid.UUID],
    window_hours: int,
    top_n: int = 5,
) -> list[dict]:
    """
    TASK-74: Fetch top entity pairs by co-occurrence weight for the brief's time window.
    Falls back to empty list if table absent.
    """
    try:
        from app.models.entity_relationship import EntityRelationship
        from app.models.entity import Entity

        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

        result = await session.execute(
            select(
                EntityRelationship.source_entity_id,
                EntityRelationship.target_entity_id,
                EntityRelationship.weight,
            )
            .where(
                EntityRelationship.last_seen >= cutoff,
                EntityRelationship.relationship_type == "cooccurrence",
            )
            .order_by(EntityRelationship.weight.desc())
            .limit(top_n)
        )
        rows = result.all()

        if not rows:
            return []

        # Resolve entity names
        all_ids = list({r[0] for r in rows} | {r[1] for r in rows})
        name_result = await session.execute(
            select(Entity.id, Entity.canonical_name).where(Entity.id.in_(all_ids))
        )
        id_to_name = {r[0]: r[1] for r in name_result.all()}

        pairs = []
        for src_id, tgt_id, weight in rows:
            src_name = id_to_name.get(src_id, str(src_id))
            tgt_name = id_to_name.get(tgt_id, str(tgt_id))
            pairs.append({
                "entity_a": src_name,
                "entity_b": tgt_name,
                "weight": round(float(weight), 3),
            })
        return pairs

    except Exception as exc:
        logger.debug("entity_cooccurrence_context: failed (non-fatal): %s", exc)
        return []


def _format_entity_pairs_note(pairs: list[dict]) -> str:
    """Format entity co-occurrence pairs for the brief prompt."""
    if not pairs:
        return ""
    lines = ["ENTITY RELATIONSHIP CONTEXT (top co-occurring pairs, last window):"]
    for p in pairs:
        lines.append(f"  • {p['entity_a']} ↔ {p['entity_b']} (weight={p['weight']})")
    return "\n".join(lines)


# ── TASK-75: JSON response parsing ────────────────────────────────────────────

def _parse_brief_json(raw: str) -> Optional[dict]:
    """
    Attempt to parse the LLM response as structured JSON.
    Returns None if parsing fails (caller falls back to raw text).
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # Validate required keys — need at least executive_summary + one other section
    if "executive_summary" not in data:
        return None
    optional_sections = {"key_developments", "entity_watch", "narrative_shifts",
                         "recommendations", "regional_breakdown", "risks_and_outlook"}
    if not optional_sections.intersection(data.keys()):
        return None

    return data


async def _build_claims_context(hours: int) -> str:
    """
    Sprint Claim Extraction CP4: Fetch active narratives with claim_text
    and build a claims context block for the brief prompt.
    """
    try:
        from app.models.narrative import Narrative as NarrativeModel, NarrativePost as NarrativePostModel  # noqa: PLC0415
        from sqlalchemy import func as sqlfunc  # noqa: PLC0415

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NarrativeModel)
                .where(
                    NarrativeModel.claim_text.isnot(None),
                    NarrativeModel.status == "active",
                    NarrativeModel.last_updated >= cutoff,
                )
                .order_by(NarrativeModel.post_count.desc())
                .limit(10)
            )
            narratives_with_claims = result.scalars().all()

            if not narratives_with_claims:
                return ""

            # Compute evidence counts per narrative (supports / contradicts)
            evidence_rows: dict[str, dict] = {}
            for narr in narratives_with_claims:
                try:
                    ev_result = await session.execute(
                        select(NarrativePostModel.evidence_role, sqlfunc.count())
                        .where(
                            NarrativePostModel.narrative_id == narr.id,
                            NarrativePostModel.evidence_role.isnot(None),
                        )
                        .group_by(NarrativePostModel.evidence_role)
                    )
                    counts: dict = {}
                    for role, cnt in ev_result.all():
                        counts[role] = cnt
                    evidence_rows[str(narr.id)] = counts
                except Exception:
                    evidence_rows[str(narr.id)] = {}

        if not narratives_with_claims:
            return ""

        lines = ["ACTIVE CLAIMS CONTEXT (from narrative intelligence, last window):"]
        contradicted_claims = []

        for narr in narratives_with_claims:
            ev = evidence_rows.get(str(narr.id), {})
            supports = ev.get("supports", 0)
            contradicts = ev.get("contradicts", 0)
            claimant_str = f" [by {narr.claimant}]" if narr.claimant else ""
            ev_str = f" | Evidence: ✓{supports} ✗{contradicts}" if (supports or contradicts) else ""
            claim_type_str = f" ({narr.claim_type})" if narr.claim_type else ""
            lines.append(
                f"  • {narr.claim_text[:200]}{claimant_str}{claim_type_str}{ev_str}"
            )
            if narr.triage_status == "contradicted":
                contradicted_claims.append(narr.claim_text[:100])

        if contradicted_claims:
            lines.append("\n  ⚠ CONTRADICTED CLAIMS (flagged by analysts):")
            for c in contradicted_claims:
                lines.append(f"    - {c}")

        return "\n".join(lines)

    except Exception as exc:
        logger.debug("_build_claims_context: failed (non-fatal): %s", exc)
        return ""


class BriefGenerator:
    """Generates AI intelligence summaries from recent posts."""

    async def generate_brief(
        self,
        user_id: str,
        hours: int = 24,
        model_id: str | None = None,
        topic: str | None = None,
        source_types: list[str] | None = None,
        custom_prompt: str | None = None,
    ) -> dict:
        """Generate an intelligence brief using the specified model.

        Args:
            topic: Optional keyword/topic filter — only posts containing this text
            source_types: Optional list of source types to include (e.g. ["rss", "telegram"])
            custom_prompt: Optional custom system prompt override
        """

        model_id = model_id or DEFAULT_MODEL
        model_config = get_model(model_id)
        if not model_config:
            if "/" in model_id or model_id not in {m["id"] for m in AI_MODELS}:
                # Try to populate cache from OpenRouter API if not already cached
                from app.services.collector_manager import collector_manager as _cm
                try:
                    or_keys = await _cm.get_keys(user_id, "openrouter")
                    if or_keys and or_keys.get("api_key"):
                        live_models = await fetch_live_openrouter_models(or_keys["api_key"])
                        if live_models:
                            cache_live_models(live_models)
                            logger.info("Populated live model cache with %d models", len(live_models))
                except Exception as exc:
                    logger.debug("Failed to fetch live models for cache: %s", exc)

                model_config = make_fallback_model_config(model_id)
                logger.info(
                    "Model '%s' resolved with context_window=%d",
                    model_id, model_config.get("context_window", 128000),
                )
            else:
                return {"error": f"Unknown model: {model_id}. Available: {[m['id'] for m in AI_MODELS]}"}

        from app.services.brief_post_selector import select_posts_for_brief

        # Determine context window limits early so we can pass budget to the selector
        # Scale post budget and content length based on model's context window
        context_window = model_config.get("context_window", 128000)
        if context_window >= 1000000:    # 1M+ (Gemini Pro, etc.)
            max_posts = 500
            max_chars = 1000
        elif context_window >= 500000:   # 500K+
            max_posts = 350
            max_chars = 800
        elif context_window >= 200000:   # 200K+ (Claude, GPT-4o)
            max_posts = 200
            max_chars = 600
        elif context_window >= 128000:   # 128K
            max_posts = 150
            max_chars = 500
        else:                            # smaller models
            max_posts = 80
            max_chars = 350

        # Smart post selection — pulls from alerts, fusion events, narratives, entities,
        # and temporal fill to ensure broad, intelligence-relevant coverage.
        selected = await select_posts_for_brief(
            hours=hours,
            budget=max_posts,
            source_types=source_types,
            topic=topic,
        )
        posts = [s["post"] for s in selected]

        if not posts:
            return {
                "summary": "No posts found in the selected time period.",
                "post_count": 0,
                "time_range_hours": hours,
                "model": model_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "confidence_score": None,
                "confidence_label": "unrated",
                "confidence_summary": "No posts available; confidence is unrated.",
                "confidence_detail": None,
            }

        post_uuids = [p.id for p in posts if p.id is not None]

        # ── Confidence computation ────────────────────────────────────────────
        confidence: dict = {}
        try:
            async with AsyncSessionLocal() as rel_session:
                confidence = await compute_brief_confidence(rel_session, post_uuids)
        except Exception as _conf_err:
            logger.debug("brief_confidence: failed to compute (non-fatal): %s", _conf_err)
            confidence = {
                "confidence_score": None,
                "confidence_label": "unrated",
                "confidence_summary": "Confidence unavailable.",
                "source_coverage": 0.0,
                "conflicting_signals": False,
                "early_signal": False,
                "rated_post_count": 0,
                "total_post_count": len(posts),
            }

        # ── TASK-73: Source reliability context ───────────────────────────────
        rel_ctx: dict = {}
        try:
            async with AsyncSessionLocal() as rel_session:
                rel_ctx = await _compute_source_reliability_context(rel_session, post_uuids)
        except Exception as exc:
            logger.debug("source_reliability_context: outer failed (non-fatal): %s", exc)

        # ── TASK-74: Entity co-occurrence context ─────────────────────────────
        entity_pairs: list[dict] = []
        try:
            async with AsyncSessionLocal() as ent_session:
                entity_pairs = await _fetch_top_entity_pairs(ent_session, post_uuids, hours)
        except Exception as exc:
            logger.debug("entity_pair_context: failed (non-fatal): %s", exc)

        post_texts = []
        for item in selected[:max_posts]:
            p = item["post"]
            reason = item["selection_reason"]
            ts_str = p.timestamp.strftime("%Y-%m-%d %H:%M UTC") if p.timestamp else "unknown time"
            text_body = (p.content or "")[:max_chars]
            post_texts.append(f"[{reason}] [{p.source_type.upper()}] [{ts_str}] {p.author}: {text_body}")

        context = "\n---\n".join(post_texts)

        # Build the system prompt
        system_prompt = custom_prompt if custom_prompt and custom_prompt.strip() else SYSTEM_PROMPT

        # Build the user message with filter context
        filter_desc_parts = []
        if topic:
            filter_desc_parts.append(f'filtered by topic "{topic}"')
        if source_types:
            filter_desc_parts.append(f"from sources: {', '.join(source_types)}")
        filter_desc = f" ({', '.join(filter_desc_parts)})" if filter_desc_parts else ""

        user_message = (
            f"Generate an intelligence brief from these {len(posts)} recent "
            f"posts (last {hours} hours{filter_desc}):\n\n{context}"
        )

        # ── Append confidence context ─────────────────────────────────────────
        if confidence:
            user_message += "\n\n" + confidence_context_block(confidence)

        # ── TASK-73: Append source reliability note ───────────────────────────
        if rel_ctx:
            reliability_note = _format_reliability_note(rel_ctx)
            if reliability_note:
                user_message += "\n\n" + reliability_note

        # ── TASK-74: Append entity co-occurrence note ─────────────────────────
        if entity_pairs:
            pairs_note = _format_entity_pairs_note(entity_pairs)
            if pairs_note:
                user_message += "\n\n" + pairs_note

        # ── Claims context (Sprint Claim Extraction CP4) ──────────────────────
        claims_note = await _build_claims_context(hours)
        if claims_note:
            user_message += "\n\n" + claims_note

        logger.info(
            "Generating brief: user=%s model=%s posts=%d hours=%d topic=%s sources=%s "
            "reliability_ctx=%s entity_pairs=%d",
            user_id, model_id, len(posts), hours, topic, source_types,
            bool(rel_ctx), len(entity_pairs),
        )

        if not model_router._providers:
            return {
                "error": "No AI provider configured for this session. Add credentials in Settings -> Credentials and log in again.",
                "post_count": len(posts),
                "time_range_hours": hours,
                "model": model_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            result = await model_router.chat(
                task="brief",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                model=model_id,
                temperature=0.3,
            )
            brief_raw = result["content"]
        except Exception as e:
            logger.error("Failed to generate brief (%s): %s", model_id, e)
            return {"error": f"Brief generation failed: {str(e)}"}

        # ── TASK-75: Parse structured JSON, fall back to raw text ─────────────
        structured: Optional[dict] = None
        brief_text: str = brief_raw

        if not (custom_prompt and custom_prompt.strip()):
            # Only attempt JSON parse when using the structured system prompt
            structured = _parse_brief_json(brief_raw)
            if structured:
                logger.info(
                    "Brief structured JSON parsed successfully for user=%s model=%s",
                    user_id, model_id,
                )
                # Reconstruct a readable plain-text summary for the `summary` field
                brief_text = structured.get("executive_summary", brief_raw)
            else:
                logger.debug(
                    "Brief JSON parse failed for user=%s model=%s — storing raw text",
                    user_id, model_id,
                )

        generated_at = datetime.now(timezone.utc)
        cost_estimate = model_config["cost_estimate_per_brief"]

        # Persist the brief
        brief_record = Brief(
            user_id=uuid.UUID(user_id),
            model=model_id,
            model_name=model_config["name"],
            hours=hours,
            post_count=len(posts),
            summary=brief_raw,  # Always store raw for fidelity
            cost_estimate=cost_estimate,
            generated_at=generated_at,
            confidence_score=confidence.get("confidence_score"),
            confidence_label=confidence.get("confidence_label"),
        )
        async with AsyncSessionLocal() as session:
            session.add(brief_record)
            await session.commit()
            await session.refresh(brief_record)
            brief_id = str(brief_record.id)

        response: dict[str, Any] = {
            "id": brief_id,
            "summary": brief_raw,
            "post_count": len(posts),
            "time_range_hours": hours,
            "model": model_id,
            "model_name": model_config["name"],
            "cost_estimate": cost_estimate,
            "generated_at": generated_at.isoformat(),
            # Confidence / reliability layer
            "confidence_score": confidence.get("confidence_score"),
            "confidence_label": confidence.get("confidence_label"),
            "confidence_summary": confidence.get("confidence_summary"),
            "confidence_detail": {
                k: confidence[k]
                for k in (
                    "source_coverage",
                    "high_confidence_fraction",
                    "low_confidence_fraction",
                    "conflicting_signals",
                    "early_signal",
                    "rated_post_count",
                    "total_post_count",
                )
                if k in confidence
            } or None,
            # TASK-73: source reliability context
            "source_reliability_context": rel_ctx or None,
            # TASK-75: structured output when available
            "structured": structured,
        }

        return response


brief_generator = BriefGenerator()
