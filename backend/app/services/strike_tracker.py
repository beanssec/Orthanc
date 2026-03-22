"""Extract daily strike/sortie counts from OSINT posts.

Scans posts for mentions of strikes, sorties, and targets by actor
(US, Israel, Iran, Hezbollah) and stores daily aggregate counts.
"""
import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, and_

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.models.strike_count import StrikeCount

logger = logging.getLogger("orthanc.strike_tracker")

# Keyword patterns for each actor
ACTOR_PATTERNS = {
    "us": [
        r"(?:US|American|CENTCOM|Pentagon|coalition)\s+(?:air)?strikes?",
        r"(?:US|American)\s+(?:sorties?|raids?|bombing)",
        r"CENTCOM\s+(?:confirms?|reports?|struck)",
        r"A-10.*(?:struck|targeted|destroyed)",
        r"F-(?:15|16|18|22|35).*(?:struck|targeted)",
    ],
    "israel": [
        r"(?:Israeli?|IDF)\s+(?:air)?strikes?",
        r"(?:Israeli?|IDF)\s+(?:sorties?|raids?|bombing|struck)",
        r"IAF\s+(?:struck|targeted|hit)",
        r"IDF\s+(?:confirms?|reports?|eliminat|struck)",
    ],
    "iran": [
        r"(?:Iranian?|IRGC)\s+(?:missile|ballistic|rocket)\s+(?:strikes?|attacks?|launches?)",
        r"(?:Iranian?|IRGC)\s+(?:struck|targeted|fired|launched)",
        r"(?:Shahab|Ghadr|Emad|Nasrallah|Fateh)\s+(?:missile|MRBM)",
    ],
    "hezbollah": [
        r"(?:Hezbollah|Hezb)\s+(?:rocket|missile|drone)\s+(?:attacks?|strikes?|barrage)",
        r"(?:Hezbollah|Hezb)\s+(?:fired|launched|struck)",
    ],
}

# Number extraction pattern — finds numbers near strike/sortie keywords
NUMBER_PATTERN = re.compile(
    r"(\d[\d,]*)\s*(?:strikes?|sorties?|targets?|rockets?|missiles?|bombs?|raids?)",
    re.IGNORECASE,
)


class StrikeTracker:
    """Extracts and tracks daily strike counts from OSINT posts."""

    async def extract_daily_counts(self, target_date: date | None = None) -> dict:
        """Extract strike counts for a given date from posts.

        Returns dict of {actor: {strike_count: N, post_count: M, post_ids: [...]}}
        """
        if target_date is None:
            target_date = date.today()

        day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        results: dict[str, dict] = {}

        async with AsyncSessionLocal() as session:
            posts_result = await session.execute(
                select(Post.id, Post.content, Post.source_type, Post.author)
                .where(
                    Post.timestamp >= day_start,
                    Post.timestamp < day_end,
                    Post.content.isnot(None),
                )
            )
            posts = posts_result.all()

        for actor, patterns in ACTOR_PATTERNS.items():
            actor_posts = []
            total_count = 0

            for post_id, content, source_type, author in posts:
                if not content:
                    continue

                matched = False
                for pattern in patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        matched = True
                        break

                if matched:
                    actor_posts.append(post_id)
                    # Try to extract specific numbers near keywords
                    numbers = NUMBER_PATTERN.findall(content)
                    for num_str in numbers:
                        try:
                            n = int(num_str.replace(",", ""))
                            if 1 <= n <= 50000:  # sanity check
                                total_count = max(total_count, n)
                        except ValueError:
                            pass

            if actor_posts:
                results[actor] = {
                    "strike_count": total_count or len(actor_posts),  # fall back to post count
                    "post_count": len(actor_posts),
                    "post_ids": actor_posts[:20],  # cap at 20 references
                }

        return results

    async def save_daily_counts(self, target_date: date | None = None) -> dict:
        """Extract and save strike counts for a date."""
        if target_date is None:
            target_date = date.today()

        counts = await self.extract_daily_counts(target_date)

        async with AsyncSessionLocal() as session:
            for actor, data in counts.items():
                existing = await session.execute(
                    select(StrikeCount).where(
                        and_(StrikeCount.date == target_date, StrikeCount.actor == actor)
                    )
                )
                record = existing.scalars().first()
                if record:
                    record.strike_count = data["strike_count"]
                    record.source_post_ids = [str(pid) for pid in data["post_ids"]]
                    record.extraction_method = "keyword"
                else:
                    record = StrikeCount(
                        date=target_date,
                        actor=actor,
                        strike_count=data["strike_count"],
                        source_post_ids=[str(pid) for pid in data["post_ids"]],
                        extraction_method="keyword",
                    )
                    session.add(record)
            await session.commit()

        logger.info(
            "Strike counts saved for %s: %s",
            target_date,
            {a: d["strike_count"] for a, d in counts.items()},
        )
        return counts

    async def backfill(self, days: int = 14) -> None:
        """Backfill strike counts for the last N days."""
        today = date.today()
        for i in range(days):
            d = today - timedelta(days=i)
            await self.save_daily_counts(d)
            logger.info("Backfilled strike counts for %s", d)

    async def start_daily_loop(self) -> None:
        """Background task: compute strike counts once per hour."""
        while True:
            try:
                await self.save_daily_counts()
            except Exception as exc:
                logger.error("Strike tracker error: %s", exc)
            await asyncio.sleep(3600)  # hourly


strike_tracker = StrikeTracker()
