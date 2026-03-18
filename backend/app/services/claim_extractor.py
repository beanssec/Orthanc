"""Claim extractor service — extracts structured claims from narrative clusters.

Calls the LLM (via model_router TASK_CLAIM_EXTRACTION) to identify:
  - The specific claim being made in a narrative
  - Who is making the claim (claimant)
  - The type of claim (victory_declaration, attribution, threat, prediction, denial, other)
  - Confidence score 0–1

Only invoked for narratives with ≥5 posts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

logger = logging.getLogger("orthanc.claim_extractor")

_LLM_TIMEOUT_SECONDS = 30

_VALID_CLAIM_TYPES = frozenset([
    "victory_declaration",
    "attribution",
    "threat",
    "prediction",
    "denial",
    "denial_of_service",
    "other",
])


class ClaimExtractor:
    """Extract claims from narrative clusters using LLM."""

    async def extract_claim(
        self,
        narrative_id: str,
        posts_summary: str,
        entity_names: list[str],
        canonical_title: str,
    ) -> Optional[dict]:
        """Extract the core claim from a narrative cluster.

        Args:
            narrative_id: UUID string (for logging).
            posts_summary: Pre-built string of post summaries (first 10, truncated).
            entity_names: Top entity names referenced in the narrative.
            canonical_title: The narrative's canonical title.

        Returns:
            dict with keys: claim_text, claimant, claim_type, confidence
            or None on failure.
        """
        from app.services.model_router import ModelRouter, model_router  # noqa: PLC0415

        entities_str = ", ".join(entity_names[:10]) if entity_names else "unknown"

        system_prompt = (
            "You are an expert OSINT analyst specialising in claim extraction from open-source intelligence.\n\n"
            "Given a set of social-media post summaries from a narrative cluster, extract the core claim.\n\n"
            "Output ONLY a JSON object with these exact keys:\n"
            '  "claim_text"   : the specific claim being made (≤60 words, declarative sentence)\n'
            '  "claimant"     : who is making or attributed with making the claim (person, org, group, or "unknown")\n'
            '  "claim_type"   : one of: victory_declaration, attribution, threat, prediction, denial, denial_of_service, other\n'
            '  "confidence"   : float 0.0–1.0 reflecting your confidence in the extraction\n\n'
            "Do NOT wrap in markdown. Do NOT explain. Output raw JSON only."
        )

        user_prompt = (
            f"NARRATIVE TITLE: {canonical_title}\n\n"
            f"KEY ENTITIES: {entities_str}\n\n"
            f"POST SUMMARIES:\n{posts_summary}\n\n"
            "Extract the core claim from these posts and return JSON:"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await asyncio.wait_for(
                model_router.chat(ModelRouter.TASK_CLAIM_EXTRACTION, messages),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            raw_content = response.get("content", "").strip()
            parsed = _safe_parse_claim_json(raw_content, narrative_id)
            if parsed:
                logger.info(
                    "Claim extracted | narrative=%s type=%s claimant=%r confidence=%.2f",
                    narrative_id,
                    parsed.get("claim_type", "?"),
                    parsed.get("claimant", "?"),
                    parsed.get("confidence", 0.0),
                )
            return parsed
        except asyncio.TimeoutError:
            logger.warning(
                "Claim extraction timed out after %ds for narrative %s",
                _LLM_TIMEOUT_SECONDS, narrative_id,
            )
            return None
        except Exception as exc:
            logger.warning(
                "Claim extraction failed for narrative %s: %s",
                narrative_id, exc,
            )
            return None


def _safe_parse_claim_json(raw: str, narrative_id) -> Optional[dict]:
    """Parse claim extraction JSON from LLM output, with fallback fence stripping."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON object via regex
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            logger.warning("Claim extractor: no JSON found in LLM output for narrative %s", narrative_id)
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("Claim extractor: JSON parse failed for narrative %s", narrative_id)
            return None

    # Validate required fields
    claim_text = str(data.get("claim_text", "")).strip()
    if not claim_text:
        logger.warning("Claim extractor: empty claim_text for narrative %s", narrative_id)
        return None

    claim_type = str(data.get("claim_type", "other")).strip().lower()
    if claim_type not in _VALID_CLAIM_TYPES:
        claim_type = "other"

    claimant = str(data.get("claimant", "unknown")).strip() or "unknown"

    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "claim_text": claim_text,
        "claimant": claimant,
        "claim_type": claim_type,
        "confidence": confidence,
    }


# Module-level singleton
claim_extractor = ClaimExtractor()
