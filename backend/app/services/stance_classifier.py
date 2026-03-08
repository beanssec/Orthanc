"""Stance classifier — classifies how each post frames a narrative event.

Two modes:
  1. AI-powered via OpenRouter (grok-3-mini) — classifies stance AND extracts claims.
  2. Keyword-based fallback — rule-based stance only, no claim extraction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from app.services.model_router import model_router

from app.db import AsyncSessionLocal
from app.models.narrative import (
    Claim,
    ClaimEvidence,
    Narrative,
    NarrativePost,
    SourceGroup,
    SourceGroupMember,
)
from app.models.post import Post
from app.models.source import Source

logger = logging.getLogger("orthanc.stance")

# ──────────────────────────────────────────────────────────────────────────────
# Prompt template
# ──────────────────────────────────────────────────────────────────────────────

STANCE_PROMPT = """Analyze how this news source covers a specific event.

NARRATIVE: {title} — {summary}

POST from {source_name} ({source_group}):
---
{content}
---

Tasks:
1. Classify the post's STANCE toward the narrative (one of: confirming, denying, attributing, contextualizing, deflecting, speculating)
2. Rate confidence (0.0 to 1.0)
3. Write a one-sentence summary of this source's take
4. Extract specific factual CLAIMS (things that can be verified)

Respond with JSON only:
{{
    "stance": "<classification>",
    "confidence": <0.0-1.0>,
    "summary": "<one sentence>",
    "claims": [
        {{"text": "<factual claim>", "type": "factual|attribution|prediction|opinion", "entities": ["entity1"], "lat": null, "lng": null}}
    ]
}}"""

# ──────────────────────────────────────────────────────────────────────────────
# Keyword dictionaries for fallback classification
# ──────────────────────────────────────────────────────────────────────────────

_DENIAL_WORDS = [
    "deny", "denied", "denies", "false", "debunk", "debunked", "disinformation",
    "hoax", "propaganda", "fabricated", "fake", "untrue", "misinformation",
    "misleading", "baseless", "unfounded", "reject", "rejected",
]
_ATTRIBUTION_WORDS = [
    "blamed", "blame", "responsible", "accused", "accuse", "perpetrated",
    "conducted by", "carried out by", "linked to", "ties to", "orchestrated",
    "mastermind", "behind the attack", "confirmed perpetrator",
]
_SPECULATION_WORDS = [
    "reportedly", "allegedly", "unconfirmed", "sources say", "rumor",
    "rumoured", "said to be", "believed to", "may have", "might have",
    "possible", "possibly", "speculated", "claim", "claims", "unclear",
    "unverified",
]
_CONTEXT_WORDS = [
    "historically", "background", "context", "analysis", "perspective",
    "in depth", "explainer", "explained", "timeline", "history of",
    "roots of", "understanding", "deep dive", "review",
]

VALID_STANCES = frozenset({
    "confirming", "denying", "attributing", "contextualizing", "deflecting", "speculating"
})


# ──────────────────────────────────────────────────────────────────────────────
# Rate limiter helpers
# ──────────────────────────────────────────────────────────────────────────────

class _RateWindow:
    """Simple token-bucket to enforce max_calls per window_seconds."""

    def __init__(self, max_calls: int, window_seconds: float):
        self._max = max_calls
        self._window = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            import time
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < self._window]
            if len(self._timestamps) >= self._max:
                sleep_for = self._window - (now - self._timestamps[0]) + 0.05
                await asyncio.sleep(max(0, sleep_for))
                now = asyncio.get_event_loop().time()
                self._timestamps = [t for t in self._timestamps if now - t < self._window]
            self._timestamps.append(now)


# ──────────────────────────────────────────────────────────────────────────────
# Main class
# ──────────────────────────────────────────────────────────────────────────────

class StanceClassifier:
    """Classify stance of posts within narratives, optionally extracting claims."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = None
        # max 5 concurrent API calls
        self._rate_limiter = asyncio.Semaphore(5)
        # max 10 per minute
        self._minute_window = _RateWindow(max_calls=10, window_seconds=60.0)

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    async def classify_narrative(self, narrative_id: uuid.UUID) -> None:
        """Classify all unclassified posts in a narrative and persist stances + claims."""
        async with AsyncSessionLocal() as session:
            # Load narrative
            narrative = await session.get(Narrative, narrative_id)
            if not narrative:
                logger.warning("classify_narrative: narrative %s not found", narrative_id)
                return

            # Get unclassified posts (stance IS NULL)
            result = await session.execute(
                select(NarrativePost)
                .where(
                    NarrativePost.narrative_id == narrative_id,
                    NarrativePost.stance.is_(None),
                )
            )
            unclassified = result.scalars().all()

        if not unclassified:
            return

        logger.info(
            "Classifying %d unclassified posts for narrative %s — %s",
            len(unclassified),
            narrative_id,
            narrative.title[:60],
        )

        for np in unclassified:
            try:
                await self._process_narrative_post(np, narrative)
            except Exception as exc:
                logger.error("Failed to classify post %s: %s", np.post_id, exc)

    async def classify_post(
        self,
        narrative_title: str,
        narrative_summary: str,
        post_content: str,
        source_name: str,
        source_group: str,
    ) -> dict:
        """Classify a single post's stance. Returns classification dict."""
        return await self._classify_ai(
            narrative_title, narrative_summary,
            post_content, source_name, source_group,
        )

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    async def _process_narrative_post(self, np: NarrativePost, narrative: Narrative) -> None:
        """Fetch post + source info, classify, persist results."""
        async with AsyncSessionLocal() as session:
            post = await session.get(Post, np.post_id)
            if not post:
                return

            # Resolve source display name and group name
            source_name, source_group_name = await self._resolve_source_info(
                session, post.source_type, post.source_id
            )

            classification = await self.classify_post(
                narrative_title=narrative.title or "",
                narrative_summary=narrative.summary or "",
                post_content=post.content or "",
                source_name=source_name,
                source_group=source_group_name,
            )

            # Validate stance
            stance = classification.get("stance", "confirming")
            if stance not in VALID_STANCES:
                stance = "confirming"

            # Update NarrativePost
            np_row = await session.get(NarrativePost, np.id)
            if np_row:
                np_row.stance = stance
                np_row.stance_confidence = float(classification.get("confidence", 0.5))
                np_row.stance_summary = classification.get("summary", "")
                session.add(np_row)

            # Extract claims (populated by AI classification, empty on keyword fallback)
            claims_data = classification.get("claims", [])
            for claim_dict in claims_data:
                    if not claim_dict.get("text"):
                        continue
                    claim = Claim(
                        narrative_id=narrative.id,
                        claim_text=claim_dict["text"][:1000],
                        claim_type=claim_dict.get("type", "factual"),
                        location_lat=claim_dict.get("lat"),
                        location_lng=claim_dict.get("lng"),
                        entity_names=claim_dict.get("entities") or [],
                        status="unverified",
                        evidence_count=0,
                        first_claimed_at=post.timestamp or datetime.now(tz=timezone.utc),
                        first_claimed_by=source_name,
                    )
                    session.add(claim)

            await session.commit()

    async def _resolve_source_info(self, session, source_type: str, source_id: str) -> tuple[str, str]:
        """Return (display_name, group_name) for a post's source."""
        # Try to find Source by handle = source_id and type = source_type
        result = await session.execute(
            select(Source).where(
                Source.type == source_type,
                Source.handle == source_id,
            ).limit(1)
        )
        source = result.scalars().first()

        if source:
            display_name = source.display_name or source.handle or source_type
            # Find group membership
            gm_result = await session.execute(
                select(SourceGroup.name)
                .join(SourceGroupMember, SourceGroup.id == SourceGroupMember.source_group_id)
                .where(SourceGroupMember.source_id == source.id)
                .limit(1)
            )
            group_name = gm_result.scalar() or "unknown"
            return display_name, group_name

        return source_type, "unknown"

    # ──────────────────────────────────────────────
    # AI classification
    # ──────────────────────────────────────────────

    async def _classify_ai(
        self,
        title: str,
        summary: str,
        content: str,
        source_name: str,
        source_group: str,
    ) -> dict:
        """AI-powered classification via OpenRouter. Falls back to keywords on error."""
        prompt = STANCE_PROMPT.format(
            title=title,
            summary=summary or "No summary available",
            content=content[:2000],
            source_name=source_name,
            source_group=source_group,
        )

        try:
            # Enforce rate limits
            await self._minute_window.acquire()
            async with self._rate_limiter:
                api_result = await model_router.chat(
                    task="stance_classification",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )

            text = api_result["content"]
            result = json.loads(text)

            # Sanitise
            if result.get("stance") not in VALID_STANCES:
                result["stance"] = "confirming"
            result.setdefault("confidence", 0.7)
            result.setdefault("summary", "")
            result.setdefault("claims", [])
            return result

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("AI classification parse error: %s — falling back", exc)
            return self._classify_keywords(content)
        except Exception as exc:
            logger.error("AI classification unexpected error: %s — falling back", exc)
            return self._classify_keywords(content)

    # ──────────────────────────────────────────────
    # Keyword fallback
    # ──────────────────────────────────────────────

    def _classify_keywords(self, content: str) -> dict:
        """Rule-based stance classification with no external API calls."""
        if not content:
            return {"stance": "confirming", "confidence": 0.1, "summary": "", "claims": []}

        lower = content.lower()

        def _count(words: list[str]) -> int:
            return sum(1 for w in words if w in lower)

        denial_hits = _count(_DENIAL_WORDS)
        attribution_hits = _count(_ATTRIBUTION_WORDS)
        speculation_hits = _count(_SPECULATION_WORDS)
        context_hits = _count(_CONTEXT_WORDS)

        scores = {
            "denying": denial_hits,
            "attributing": attribution_hits,
            "speculating": speculation_hits,
            "contextualizing": context_hits,
        }

        best_stance = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_count = scores[best_stance]

        if best_count == 0:
            # default
            return {"stance": "confirming", "confidence": 0.3, "summary": "", "claims": []}

        confidence = min(0.7, best_count / 10)
        return {
            "stance": best_stance,
            "confidence": confidence,
            "summary": "",
            "claims": [],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

stance_classifier = StanceClassifier()
