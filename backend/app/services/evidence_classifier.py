"""Evidence classifier service — Sprint Claim Extraction CP2.

Classifies posts relative to a narrative's claim:
  supports | contradicts | contextual | unclear

Uses the cheap TASK_CLAIM_EXTRACTION model via model_router.
Batches up to 20 posts per LLM call.
"""
import asyncio
import json
import logging
import re
from typing import Optional

logger = logging.getLogger("orthanc.evidence_classifier")

# Valid roles the LLM is allowed to return
_VALID_ROLES = frozenset({"supports", "contradicts", "contextual", "unclear"})

# Max posts per single LLM batch call
_BATCH_SIZE = 20

# Timeout per LLM call (seconds)
_LLM_TIMEOUT = 45


class EvidenceClassifier:
    """Classify posts relative to a narrative's claim."""

    async def classify_evidence(
        self,
        claim_text: str,
        claimant: str,
        posts: list[dict],
    ) -> list[dict]:
        """
        Classify a list of posts relative to a claim.

        Args:
            claim_text: The claim being evaluated.
            claimant:   Who is making the claim.
            posts:      List of {"post_id": str, "content": str} dicts.

        Returns:
            List of {"post_id": str, "role": str, "confidence": float} dicts.
            Posts that fail classification are skipped (not returned).
        """
        if not posts or not claim_text:
            return []

        try:
            from app.services.model_router import model_router, ModelRouter  # noqa: PLC0415
        except ImportError as exc:
            logger.debug("model_router not importable — skipping evidence classification: %s", exc)
            return []

        if not model_router._providers:
            logger.debug("No LLM providers registered — skipping evidence classification")
            return []

        results: list[dict] = []

        # Process in batches of _BATCH_SIZE
        for i in range(0, len(posts), _BATCH_SIZE):
            batch = posts[i : i + _BATCH_SIZE]
            batch_results = await self._classify_batch(
                model_router=model_router,
                task=ModelRouter.TASK_CLAIM_EXTRACTION,
                claim_text=claim_text,
                claimant=claimant,
                batch=batch,
            )
            results.extend(batch_results)

        return results

    async def _classify_batch(
        self,
        model_router,
        task: str,
        claim_text: str,
        claimant: str,
        batch: list[dict],
    ) -> list[dict]:
        """Run a single LLM batch call for up to _BATCH_SIZE posts."""
        # Build the post listing for the prompt
        post_lines = []
        for idx, p in enumerate(batch):
            post_id = p.get("post_id", f"post_{idx}")
            content = (p.get("content") or "").strip()[:300]
            post_lines.append(f'{idx + 1}. [ID: {post_id}] "{content}"')

        posts_text = "\n".join(post_lines)

        system_prompt = (
            "You are an expert OSINT evidence analyst. "
            "Given a claim and a list of social-media posts, classify each post's "
            "relationship to the claim.\n\n"
            "Classification values:\n"
            "  supports     — post provides evidence that the claim is true\n"
            "  contradicts  — post provides evidence that the claim is false or challenged\n"
            "  contextual   — post is related to the claim's topic but does not confirm or deny it\n"
            "  unclear      — post is unrelated, ambiguous, or too sparse to classify\n\n"
            "Output ONLY a JSON array with one object per post:\n"
            '[{"post_id": "<id>", "role": "<role>", "confidence": <0.0-1.0>}, ...]\n\n'
            "Do NOT wrap in markdown. Do NOT explain. Output raw JSON array only."
        )

        user_prompt = (
            f'CLAIM: "{claim_text}"\n'
            f"CLAIMANT: {claimant or 'unknown'}\n\n"
            f"POSTS TO CLASSIFY:\n{posts_text}\n\n"
            "Return JSON classification array:"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await asyncio.wait_for(
                model_router.chat(task, messages),
                timeout=_LLM_TIMEOUT,
            )
            raw_content = response.get("content", "").strip()
            return self._parse_classification_response(raw_content, batch)
        except asyncio.TimeoutError:
            logger.warning(
                "Evidence classification LLM call timed out after %ds for %d posts",
                _LLM_TIMEOUT,
                len(batch),
            )
            return []
        except Exception as exc:
            logger.warning(
                "Evidence classification LLM call failed for %d posts: %s",
                len(batch),
                exc,
            )
            return []

    def _parse_classification_response(
        self,
        raw: str,
        batch: list[dict],
    ) -> list[dict]:
        """
        Parse the LLM JSON response with fallback for markdown fences.

        Returns validated list of {"post_id": str, "role": str, "confidence": float}.
        """
        # Strip markdown fences if present
        text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

        # Sometimes the LLM wraps in an object: {"classifications": [...]}
        # Try to extract the array
        if text.startswith("{"):
            # Look for an array value inside
            arr_match = re.search(r"\[.*\]", text, re.DOTALL)
            if arr_match:
                text = arr_match.group(0)

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug(
                "Evidence classifier JSON parse failed: %s | raw=%r",
                exc,
                raw[:300],
            )
            return []

        if not isinstance(data, list):
            logger.debug("Evidence classifier: expected JSON array, got %s", type(data).__name__)
            return []

        # Build a lookup of valid post_ids from this batch
        valid_post_ids = {p.get("post_id") for p in batch if p.get("post_id")}

        results: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            post_id = item.get("post_id")
            if not isinstance(post_id, str) or post_id not in valid_post_ids:
                continue

            role = item.get("role")
            if not isinstance(role, str) or role.strip().lower() not in _VALID_ROLES:
                # Default to "unclear" rather than dropping
                role = "unclear"
            else:
                role = role.strip().lower()

            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0:
                confidence = round(float(confidence), 3)
            else:
                confidence = 0.5  # neutral default

            results.append({
                "post_id": post_id,
                "role": role,
                "confidence": confidence,
            })

        return results


# Singleton
evidence_classifier = EvidenceClassifier()
