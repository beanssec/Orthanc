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
  "changes_since_last": {
    "new": ["<development that was NOT in the previous brief — tag as genuinely new>", "..."],
    "updated": ["<situation from previous brief that has evolved or changed — describe what changed>", "..."],
    "quiet": ["<topic from previous brief that is no longer appearing in current sources>", "..."]
  },
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
    "CRITICAL — ANALYTICAL NEUTRALITY:\n"
    "- Report WHAT sources say happened, not WHO is right or wrong\n"
    "- Do NOT use loaded terms like 'belligerent', 'aggressor', 'regime', 'terrorist' unless directly quoting a source — and if so, attribute it\n"
    "- Describe actions factually: 'X conducted strikes on Y' not 'X attacked Y'\n"
    "- When sources disagree, present BOTH sides with attribution ('Source A claims... while Source B reports...')\n"
    "- Entity roles should describe observable actions and posture, not assign moral judgement\n"
    "- Distinguish between confirmed events (multi-source) and single-source claims\n"
    "- Flag unverified claims explicitly\n\n"
    "You will receive three types of context:\n"
    "1. ACTIVE STORYLINES — compressed summaries of evolving intelligence arcs, each representing dozens to hundreds of posts\n"
    "2. INDIVIDUAL POSTS — the most significant recent posts, tagged with their selection reason (ALERT, FUSION, NARRATIVE, TRENDING, TEMPORAL)\n"
    "3. SOURCE DIVERGENCE — events where different source groups (Western, Iranian, Russian, etc.) significantly disagree. "
    "Flag these disagreements explicitly in your analysis and attribute claims to source groups.\n"
    "Use storyline summaries for big-picture context and trend analysis. Use individual posts for specific details and fresh developments.\n"
    "Weight ALERT and FUSION tagged posts highest.\n\n"
    "Return ONLY a valid JSON object matching this schema (no markdown fences, no explanation):\n"
    f"{BRIEF_JSON_SCHEMA}\n\n"
    "BREVITY IS CRITICAL. This is a BRIEF, not an encyclopaedia. Each section has strict limits.\n\n"
    "Requirements:\n"
    "- executive_summary: 4-6 sentences ONLY. LEAD WITH WHAT CHANGED in the last cycle — do NOT open with generic framing like 'The conflict continues to escalate'. Start with the most significant NEW development or shift. Only then provide 1-2 sentences of broader context. A reader of the previous brief should immediately see what is different TODAY.\n"
    "- changes_since_last: compare against PREVIOUS BRIEF if provided. MAX 5 new, 5 updated, 3 quiet. Group related items — do NOT list every individual post as a separate item. CRITICAL: every item from the previous brief's NEW section MUST appear in either UPDATED (if still developing) or QUIET (if no longer appearing). Do NOT silently drop tracked items. If no previous brief, omit or leave empty.\n"
    "- key_developments: 8-12 items. One sentence each with specifics (who, what, where, when). Attribute sources in parentheses. Do NOT write paragraphs.\n"
    "- regional_breakdown: 2-4 regions. Each summary is 2-3 sentences MAX.\n"
    "- entity_watch: 5-8 key actors. Role is ONE sentence. Note is 2-3 sentences MAX. Include at least 1-2 EMERGING entities not present in the previous brief's entity watch — new actors, newly relevant organisations, or individuals whose role has changed significantly.\n"
    "- narrative_shifts: 3-5 items. One sentence each describing WHAT shifted and WHY it matters. These MUST be changes from the previous cycle — not ongoing situations. If a narrative appeared in the last brief, only include it here if its trajectory, framing, or source consensus has measurably changed.\n"
    "- risks_and_outlook: 3-5 items. One sentence each.\n"
    "- recommendations: 3-5 items. Each must be SPECIFIC and ACTIONABLE — name the intelligence discipline (SIGINT, IMINT, OSINT, HUMINT), the specific target or collection focus, and the timeframe or trigger. Bad: 'Monitor Iran's nuclear program.' Good: 'Task IMINT collection on Bushehr and Arak facilities within 48h to assess post-strike damage extent.' Do NOT use generic verbs like 'monitor' or 'assess' without specifying what, how, and why now.\n\n"
    "Be analytical and impartial. Cite sources. An intelligence brief reports facts — it does not take sides. "
    "Prioritise significance over comprehensiveness — a decision-maker should read this in under 5 minutes."
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
    Includes repair logic for truncated responses (missing closing brackets/braces).
    Returns None if parsing fails (caller falls back to raw text).
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # First try direct parse
    data = _try_json_load(text)

    # If that fails, attempt truncation repair
    if data is None:
        data = _repair_truncated_json(text)

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


def _try_json_load(text: str) -> Optional[dict]:
    """Try to parse JSON, return None on failure."""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_truncated_json(text: str) -> Optional[dict]:
    """
    Attempt to repair JSON that was truncated mid-output (e.g. due to max_tokens).
    Strategy: find the last valid value boundary, close open strings/arrays/objects.
    """
    if not text or text[0] != '{':
        return None

    # Find the last cleanly closed property value
    # Look for the last complete key-value pair by finding last '", "' or '"], "'
    # Then truncate there and close the structure

    # Strategy 1: Trim to last complete array item or string value
    # Find last position where we have a complete value followed by a comma or bracket
    last_good = -1
    for pattern in [
        r'"\s*\]\s*,',   # end of a string array followed by comma (next key coming)
        r'"\s*\]\s*\}',  # end of a string array followed by object close
        r'"\s*,\s*"',    # end of a string value followed by comma and next key
        r'\}\s*\]\s*,',  # end of object array followed by comma
    ]:
        for match in re.finditer(pattern, text):
            pos = match.end()
            if pos > last_good:
                last_good = pos

    if last_good < len(text) // 2:
        # Too much data lost — don't attempt repair
        return None

    # Truncate to last good position
    truncated = text[:last_good].rstrip().rstrip(',')

    # Count unclosed brackets and braces
    open_braces = truncated.count('{') - truncated.count('}')
    open_brackets = truncated.count('[') - truncated.count(']')

    # Close them
    truncated += ']' * max(0, open_brackets)
    truncated += '}' * max(0, open_braces)

    result = _try_json_load(truncated)
    if result:
        logger.info("Repaired truncated brief JSON (trimmed %d chars, closed %d brackets + %d braces)",
                     len(text) - last_good, max(0, open_brackets), max(0, open_braces))
    return result


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
        max_tokens = model_config.get("max_completion_tokens", 16384)
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

        # ── Arc storyline context ──────────────────────────────────────────────
        arc_context_text = ""
        try:
            from app.services.brief_post_selector import fetch_arc_context
            arcs = await fetch_arc_context(hours=hours, max_arcs=20)
            if arcs:
                arc_lines = []
                for arc in arcs:
                    first = arc.get("first_seen", "")
                    if first:
                        try:
                            from datetime import datetime as dt
                            first = dt.fromisoformat(first).strftime("%b %d") if isinstance(first, str) else first.strftime("%b %d")
                        except Exception:
                            pass
                    arc_lines.append(
                        f"• {arc['title']} ({arc['arc_type'] or 'other'}, "
                        f"{arc['narrative_count']} events, {arc['total_post_count']} posts since {first})\n"
                        f"  {arc['summary']}"
                    )
                arc_context_text = "\n".join(arc_lines)
                logger.info("Brief: injecting %d arc storyline summaries", len(arcs))
        except Exception as exc:
            logger.debug("Arc context injection failed (non-fatal): %s", exc)

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

        if arc_context_text:
            user_message += (
                "\n\nACTIVE STORYLINES (compressed summaries covering all collected intelligence — "
                "these represent thousands of posts you don't see individually):\n"
                f"{arc_context_text}\n\n"
                "Use these storyline summaries as background context. The individual posts above "
                "provide the latest specific details. Your brief should reflect BOTH the broader "
                "storyline arcs AND the fresh individual posts."
            )

        # ── Source divergence context ─────────────────────────────────────────
        divergence_text = ""
        try:
            from app.services.brief_post_selector import fetch_divergence_context
            divergent_events = await fetch_divergence_context(hours=hours)
            if divergent_events:
                div_lines = []
                for evt in divergent_events:
                    groups_str = ", ".join(
                        f"{g}: {s}" for g, s in evt.get("groups", {}).items()
                    )
                    div_lines.append(
                        f"• {evt['title']} (divergence={evt['divergence_score']:.2f}): {groups_str}"
                    )
                divergence_text = "\n".join(div_lines)
                logger.info("Brief: injecting %d high-divergence events", len(divergent_events))
        except Exception as exc:
            logger.debug("Divergence context injection failed (non-fatal): %s", exc)

        if divergence_text:
            user_message += (
                "\n\nSOURCE DIVERGENCE (events where source groups significantly disagree on interpretation):\n"
                f"{divergence_text}\n\n"
                "These events have conflicting coverage across source groups. "
                "In your brief, note these disagreements explicitly and attribute claims to their source groups."
            )

        # ── Previous brief context for change detection ───────────────────────
        logger.info("Attempting previous brief lookup for user %s", user_id)
        try:
            async with AsyncSessionLocal() as prev_session:
                prev_result = await prev_session.execute(
                    select(Brief)
                    .where(Brief.user_id == uuid.UUID(user_id))
                    .order_by(Brief.generated_at.desc())
                    .limit(1)
                )
                prev_brief = prev_result.scalars().first()
                if prev_brief and prev_brief.summary:
                    # Extract key points from previous brief for comparison
                    prev_summary = prev_brief.summary
                    # Truncate to avoid blowing context — just need the key developments and executive summary
                    prev_parsed = _parse_brief_json(prev_summary)
                    if prev_parsed:
                        prev_context_parts = []
                        if prev_parsed.get("executive_summary"):
                            prev_context_parts.append(f"Executive Summary: {prev_parsed['executive_summary']}")
                        if prev_parsed.get("key_developments"):
                            devs = "\n".join(f"- {d}" for d in prev_parsed["key_developments"][:15])
                            prev_context_parts.append(f"Key Developments:\n{devs}")
                        if prev_parsed.get("changes_since_last", {}).get("new"):
                            new_items = "\n".join(f"- {n}" for n in prev_parsed["changes_since_last"]["new"][:10])
                            prev_context_parts.append(f"Items flagged as NEW in previous brief:\n{new_items}")
                        prev_context = "\n\n".join(prev_context_parts)
                    else:
                        # Fallback for markdown briefs — just use first 2000 chars
                        prev_context = prev_summary[:2000]

                    prev_generated = prev_brief.generated_at.strftime("%Y-%m-%d %H:%M UTC") if prev_brief.generated_at else "unknown"
                    user_message += (
                        f"\n\nPREVIOUS BRIEF (generated {prev_generated}):\n"
                        f"{prev_context}\n\n"
                        f"IMPORTANT: Compare current intelligence against the previous brief above. "
                        f"In the 'changes_since_last' section:\n"
                        f"- 'new': list developments that are genuinely NEW and were NOT covered in the previous brief\n"
                        f"- 'updated': list situations from the previous brief that have EVOLVED or CHANGED — describe specifically what changed\n"
                        f"- 'quiet': list topics from the previous brief that are NO LONGER appearing in current sources\n"
                        f"If there is no previous brief, leave changes_since_last empty."
                    )
                    logger.info(
                        "Attached previous brief context (generated %s) for change detection",
                        prev_generated,
                    )
        except Exception as exc:
            logger.warning("Failed to fetch previous brief for change detection: %s", exc)

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
            "reliability_ctx=%s entity_pairs=%d max_tokens=%d",
            user_id, model_id, len(posts), hours, topic, source_types,
            bool(rel_ctx), len(entity_pairs), max_tokens,
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
                max_tokens=max_tokens,
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
