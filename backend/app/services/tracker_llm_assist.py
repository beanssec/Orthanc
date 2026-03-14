"""LLM-assisted refinement for tracked narrative matching.

This module provides an *optional* hook that runs after heuristic candidate
selection in ``_recompute_tracker``.  It is only activated when a tracker's
``model_policy`` explicitly enables it, and it degrades gracefully to the
heuristic result on any failure.

Model-policy schema (JSONB on NarrativeTracker.model_policy)
------------------------------------------------------------
{
  "enabled": true,            // required — must be true to activate
  "max_candidates": 10,       // optional — cap LLM calls per recompute (default 10)
  "model": "grok-3-mini",     // optional — override the default task model
  "task": "tracked_narrative_match"  // optional — override task key for routing
}

The LLM is asked to evaluate, for each heuristic-selected narrative, whether
it *supports*, *contradicts*, is *contextual*, or *unclear* with respect to
the tracker's hypothesis.  The response is a single token from that vocabulary.
If parsing fails or the call errors, the heuristic ``evidence_relation`` is
preserved unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.narrative import Narrative, NarrativeTracker
    from app.services.model_router import ModelRouter

logger = logging.getLogger("orthanc.tracker_llm_assist")

# Allowed relation values — anything else from the model is rejected
VALID_RELATIONS = frozenset({"supports", "contradicts", "contextual", "unclear"})

_SYSTEM_PROMPT = (
    "You are an OSINT intelligence analyst. "
    "Given a tracker hypothesis and a narrative summary, classify how the "
    "narrative relates to the hypothesis.\n"
    "Reply with EXACTLY one word from this list: "
    "supports | contradicts | contextual | unclear\n"
    "No explanation. No punctuation. Just the single word."
)


def _llm_enabled(model_policy: dict | None) -> bool:
    """Return True only when model_policy explicitly opts in."""
    if not isinstance(model_policy, dict):
        return False
    return bool(model_policy.get("enabled"))


def _policy_get(model_policy: dict, key: str, default):
    """Safe getter for model_policy values."""
    return model_policy.get(key, default)


def _build_user_prompt(
    tracker_name: str,
    hypothesis: str | None,
    narrative_title: str,
    narrative_summary: str | None,
    canonical_claim: str | None,
    topic_keywords: list[str],
) -> str:
    parts = [f"TRACKER: {tracker_name}"]
    if hypothesis:
        parts.append(f"HYPOTHESIS: {hypothesis}")
    parts.append(f"NARRATIVE TITLE: {narrative_title}")
    if canonical_claim:
        parts.append(f"CANONICAL CLAIM: {canonical_claim}")
    if narrative_summary:
        parts.append(f"SUMMARY: {narrative_summary[:600]}")
    if topic_keywords:
        parts.append(f"KEYWORDS: {', '.join(topic_keywords[:10])}")
    return "\n".join(parts)


async def llm_refine_evidence_relation(
    tracker: "NarrativeTracker",
    narrative: "Narrative",
    heuristic_relation: str,
    model_router: "ModelRouter",
) -> str:
    """Use an LLM to refine a single narrative's evidence_relation.

    Returns the refined relation string, or ``heuristic_relation`` on any
    error (fail-safe).
    """
    mp: dict = tracker.model_policy or {}
    task = _policy_get(mp, "task", "tracked_narrative_match")
    model_override = _policy_get(mp, "model", None)

    user_prompt = _build_user_prompt(
        tracker_name=tracker.name,
        hypothesis=tracker.hypothesis,
        narrative_title=narrative.title or "",
        narrative_summary=narrative.summary,
        canonical_claim=narrative.canonical_claim,
        topic_keywords=narrative.topic_keywords or [],
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    kwargs: dict = {"max_tokens": 10, "temperature": 0}
    if model_override:
        kwargs["model"] = model_override

    try:
        result = await model_router.chat(task, messages, **kwargs)
        raw = (result.get("content") or "").strip().lower()
        # Strip punctuation and take first word
        token = raw.split()[0].rstrip(".,;:") if raw.split() else ""
        if token in VALID_RELATIONS:
            logger.debug(
                "LLM refined evidence_relation: %s → %s (narrative=%s, tracker=%s)",
                heuristic_relation, token, narrative.id, tracker.id,
            )
            return token
        else:
            logger.warning(
                "LLM returned unexpected relation '%s' for narrative=%s; "
                "keeping heuristic '%s'",
                raw, narrative.id, heuristic_relation,
            )
            return heuristic_relation
    except Exception as exc:
        logger.warning(
            "LLM refinement failed for narrative=%s tracker=%s: %s — "
            "falling back to heuristic '%s'",
            narrative.id, tracker.id, exc, heuristic_relation,
        )
        return heuristic_relation


async def llm_refine_batch(
    tracker: "NarrativeTracker",
    candidates: list[tuple["Narrative", float, bool, bool, str]],
    model_router: "ModelRouter",
) -> list[tuple["Narrative", float, bool, bool, str]]:
    """Refine evidence_relation for a batch of heuristic candidates.

    ``candidates`` is a list of tuples:
        (narrative, match_score, pattern_matched, entity_matched, heuristic_relation)

    Returns the same structure with evidence_relation potentially updated by the
    model.  Heuristic values are preserved for any narrative where the model
    call fails.

    Only processes up to ``model_policy.max_candidates`` (default 10) top-scored
    narratives to bound costs.  Remaining narratives keep their heuristic labels.
    """
    mp: dict = tracker.model_policy or {}
    max_candidates: int = int(_policy_get(mp, "max_candidates", 10))

    # Sort by match_score descending, process top N
    sorted_candidates = sorted(candidates, key=lambda t: t[1], reverse=True)
    to_refine = sorted_candidates[:max_candidates]
    rest = sorted_candidates[max_candidates:]

    refined: list[tuple["Narrative", float, bool, bool, str]] = []
    for narrative, score, pat_matched, ent_matched, heuristic_rel in to_refine:
        refined_rel = await llm_refine_evidence_relation(
            tracker=tracker,
            narrative=narrative,
            heuristic_relation=heuristic_rel,
            model_router=model_router,
        )
        refined.append((narrative, score, pat_matched, ent_matched, refined_rel))

    return refined + rest
