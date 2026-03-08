"""Narrative clustering engine — groups posts about the same real-world events."""
import asyncio
import logging
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, update

from app.db import AsyncSessionLocal
from app.models.narrative import Narrative, NarrativePost, PostEmbedding
from app.models.post import Post
from app.services.embedding_service import embedding_service

logger = logging.getLogger("orthanc.narrative")

# ──────────────────────────────────────────────
# Maths helpers
# ──────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def centroid(vectors: list[list[float]]) -> list[float]:
    """Mean vector (centroid) of a list of equal-length vectors."""
    if not vectors:
        return []
    dim = len(vectors[0])
    c = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            c[i] += v[i]
    n = len(vectors)
    return [x / n for x in c]


# ──────────────────────────────────────────────
# Stop-words for title generation
# ──────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "and", "but", "or",
    "nor", "not", "no", "so", "yet", "both", "either", "neither", "each",
    "every", "all", "any", "few", "more", "most", "other", "some", "such",
    "than", "too", "very", "just", "also", "only", "own", "same", "then",
    "that", "this", "these", "those", "what", "which", "who", "whom",
    "how", "when", "where", "why", "if", "for", "from", "in", "on", "at",
    "to", "of", "with", "by", "about", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "once", "here", "there", "it", "its",
    "he", "she", "they", "them", "his", "her", "their", "we", "you", "i",
    "me", "my", "your", "our", "up", "down", "new", "said", "says",
    "according", "https", "http", "www", "com", "rt", "via",
})


# ──────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────

class NarrativeEngine:
    """
    Background service that clusters posts into narratives.

    Cycle (every POLL_INTERVAL seconds):
      1. Embed any unembedded posts from the last LOOKBACK_HOURS.
      2. Try to add new embeddings to existing active narratives.
      3. Cluster remaining unassigned posts into brand-new narratives.
      4. Refresh post_count / source_count on all active narratives.
      5. Mark narratives with no recent activity as stale.
    """

    # ── Tuning knobs ──────────────────────────
    CLUSTER_SIMILARITY = 0.70       # min similarity to join an existing narrative
    NEW_CLUSTER_SIMILARITY = 0.75   # min similarity for initial greedy clustering
    MIN_POSTS_FOR_NARRATIVE = 3     # a cluster needs at least this many posts …
    MIN_SOURCES_FOR_NARRATIVE = 2   # … from at least this many distinct source_types
    STALE_HOURS = 12                # mark active narrative stale after N quiet hours
    LOOKBACK_HOURS = 24             # only consider posts from the last N hours
    POLL_INTERVAL = 600             # seconds between full cycles (10 min)
    MAX_POSTS_PER_CYCLE = 200       # max posts to embed in one cycle

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Narrative clustering engine started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Narrative clustering engine stopped")

    # ──────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:
                logger.exception("Narrative engine cycle error: %s", exc)
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _cycle(self) -> None:
        """One full clustering cycle."""
        embedded = await self._embed_new_posts()
        if embedded:
            logger.info("Narrative engine: embedded %d new posts", embedded)

        assigned = await self._assign_to_existing_narratives()
        if assigned:
            logger.info("Narrative engine: assigned %d posts to existing narratives", assigned)

        created = await self._create_new_narratives()
        if created:
            logger.info("Narrative engine: created %d new narratives", created)

        await self._update_narrative_stats()
        await self._mark_stale_narratives()

    # ──────────────────────────────────────────
    # Step 1 — embed new posts
    # ──────────────────────────────────────────

    async def _embed_new_posts(self) -> int:
        """Embed posts from the last LOOKBACK_HOURS that have no embedding yet."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.LOOKBACK_HOURS)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Post.id, Post.content)
                .outerjoin(PostEmbedding, PostEmbedding.post_id == Post.id)
                .where(
                    Post.timestamp >= cutoff,
                    PostEmbedding.post_id.is_(None),
                    Post.content.isnot(None),
                    func.length(Post.content) > 50,
                )
                .limit(self.MAX_POSTS_PER_CYCLE)
            )
            rows = result.all()

        if not rows:
            return 0

        post_ids = [r[0] for r in rows]
        texts = [r[1][:2000] for r in rows]

        try:
            embeddings = await embedding_service.embed_batch(texts)
        except Exception as exc:
            logger.error("Embedding batch failed: %s", exc)
            return 0

        model_name = "text-embedding-3-small"

        async with AsyncSessionLocal() as session:
            for post_id, emb in zip(post_ids, embeddings):
                pe = PostEmbedding(
                    post_id=post_id,
                    embedding=emb,
                    model=model_name,
                )
                session.add(pe)
            await session.commit()

        return len(post_ids)

    # ──────────────────────────────────────────
    # Step 2 — assign to existing narratives
    # ──────────────────────────────────────────

    async def _assign_to_existing_narratives(self) -> int:
        """
        For each unassigned embedded post, compute its similarity to the
        centroid of every active narrative and assign it to the closest one
        if similarity ≥ CLUSTER_SIMILARITY.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.LOOKBACK_HOURS)
        assigned = 0

        # Fetch active narratives
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Narrative.id).where(Narrative.status == "active")
            )
            narrative_ids = [r[0] for r in result.all()]

        if not narrative_ids:
            return 0

        # Build centroid for each narrative
        narrative_centroids: dict = {}
        for nid in narrative_ids:
            async with AsyncSessionLocal() as session:
                emb_result = await session.execute(
                    select(PostEmbedding.embedding)
                    .join(NarrativePost, NarrativePost.post_id == PostEmbedding.post_id)
                    .where(NarrativePost.narrative_id == nid)
                    .limit(20)
                )
                embs = [r[0] for r in emb_result.all()]
            if embs:
                narrative_centroids[nid] = centroid(embs)

        if not narrative_centroids:
            return 0

        # Fetch unassigned embedded posts from the last 24 h
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PostEmbedding.post_id, PostEmbedding.embedding)
                .outerjoin(NarrativePost, NarrativePost.post_id == PostEmbedding.post_id)
                .join(Post, Post.id == PostEmbedding.post_id)
                .where(
                    NarrativePost.id.is_(None),
                    Post.timestamp >= cutoff,
                )
                .limit(100)
            )
            candidates = result.all()

        for post_id, embedding in candidates:
            best_nid = None
            best_sim = 0.0

            for nid, cent in narrative_centroids.items():
                sim = cosine_similarity(embedding, cent)
                if sim > best_sim:
                    best_sim = sim
                    best_nid = nid

            if best_nid and best_sim >= self.CLUSTER_SIMILARITY:
                async with AsyncSessionLocal() as session:
                    np = NarrativePost(narrative_id=best_nid, post_id=post_id)
                    session.add(np)
                    try:
                        await session.commit()
                        assigned += 1
                        # Keep centroid fresh (cheap approximation: just append new vector)
                        narrative_centroids[best_nid] = centroid(
                            [narrative_centroids[best_nid], embedding]
                        )
                    except Exception:
                        await session.rollback()  # unique-constraint violation → already assigned

        return assigned

    # ──────────────────────────────────────────
    # Step 3 — create new narratives
    # ──────────────────────────────────────────

    async def _create_new_narratives(self) -> int:
        """
        Greedy clustering of unassigned posts.

        For each seed post, collect every other unassigned post whose
        cosine similarity to the seed exceeds NEW_CLUSTER_SIMILARITY.
        If the resulting cluster has ≥ MIN_POSTS_FOR_NARRATIVE posts from
        ≥ MIN_SOURCES_FOR_NARRATIVE distinct source_types, persist it as a
        new Narrative.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.LOOKBACK_HOURS)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    PostEmbedding.post_id,
                    PostEmbedding.embedding,
                    Post.source_type,
                    Post.content,
                    Post.timestamp,
                )
                .join(Post, Post.id == PostEmbedding.post_id)
                .outerjoin(NarrativePost, NarrativePost.post_id == PostEmbedding.post_id)
                .where(
                    NarrativePost.id.is_(None),
                    Post.timestamp >= cutoff,
                )
                .limit(300)
            )
            posts = result.all()

        if len(posts) < self.MIN_POSTS_FOR_NARRATIVE:
            return 0

        used: set = set()
        clusters = []

        for i, (pid_i, emb_i, st_i, content_i, ts_i) in enumerate(posts):
            if pid_i in used:
                continue

            cluster = [(pid_i, emb_i, st_i, content_i, ts_i)]
            used.add(pid_i)

            for pid_j, emb_j, st_j, content_j, ts_j in posts:
                if pid_j in used:
                    continue
                if cosine_similarity(emb_i, emb_j) >= self.NEW_CLUSTER_SIMILARITY:
                    cluster.append((pid_j, emb_j, st_j, content_j, ts_j))
                    used.add(pid_j)

            if len(cluster) < self.MIN_POSTS_FOR_NARRATIVE:
                continue
            source_types = {c[2] for c in cluster}
            if len(source_types) < self.MIN_SOURCES_FOR_NARRATIVE:
                continue

            clusters.append(cluster)

        created = 0
        for cluster in clusters:
            post_ids = [c[0] for c in cluster]
            contents = [c[3] for c in cluster if c[3]]
            timestamps = [c[4] for c in cluster if c[4]]
            source_types = {c[2] for c in cluster}

            title = self._generate_title(contents)
            summary = self._generate_summary(contents)
            first_seen = min(timestamps) if timestamps else datetime.now(timezone.utc)

            async with AsyncSessionLocal() as session:
                narrative = Narrative(
                    title=title,
                    summary=summary,
                    status="active",
                    first_seen=first_seen,
                    last_updated=datetime.now(timezone.utc),
                    post_count=len(post_ids),
                    source_count=len(source_types),
                )
                session.add(narrative)
                await session.flush()  # populate narrative.id

                for pid in post_ids:
                    session.add(NarrativePost(narrative_id=narrative.id, post_id=pid))

                await session.commit()
                created += 1
                logger.info(
                    "New narrative '%s' — %d posts from %d source types",
                    title,
                    len(post_ids),
                    len(source_types),
                )

        return created

    # ──────────────────────────────────────────
    # Step 4 — refresh stats
    # ──────────────────────────────────────────

    async def _update_narrative_stats(self) -> None:
        """Recompute post_count and source_count for all active narratives."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Narrative).where(Narrative.status == "active")
            )
            narratives = result.scalars().all()

            for narr in narratives:
                post_count_result = await session.execute(
                    select(func.count())
                    .select_from(NarrativePost)
                    .where(NarrativePost.narrative_id == narr.id)
                )
                narr.post_count = post_count_result.scalar() or 0

                source_count_result = await session.execute(
                    select(func.count(func.distinct(Post.source_type)))
                    .join(NarrativePost, NarrativePost.post_id == Post.id)
                    .where(NarrativePost.narrative_id == narr.id)
                )
                narr.source_count = source_count_result.scalar() or 0

            await session.commit()

    # ──────────────────────────────────────────
    # Step 5 — mark stale narratives
    # ──────────────────────────────────────────

    async def _mark_stale_narratives(self) -> None:
        """Demote active narratives that have had no updates for STALE_HOURS."""
        stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.STALE_HOURS)

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Narrative)
                .where(
                    Narrative.status == "active",
                    Narrative.last_updated < stale_cutoff,
                )
                .values(status="stale")
            )
            await session.commit()

    # ──────────────────────────────────────────
    # Text utilities
    # ──────────────────────────────────────────

    def _generate_title(self, contents: list[str]) -> str:
        """
        Derive a short title from the most frequent non-stop words across
        the first 10 posts in the cluster.
        """
        words: Counter = Counter()
        for content in contents[:10]:
            if not content:
                continue
            for raw in content.lower().split():
                word = raw.strip(".,!?:;\"'()[]{}#@")
                if (
                    len(word) > 2
                    and word not in _STOP_WORDS
                    and not word.startswith("http")
                ):
                    words[word] += 1

        top = words.most_common(5)
        if not top:
            return "Unclassified Event"

        return " ".join(w.title() for w, _ in top[:4])

    def _generate_summary(self, contents: list[str]) -> str:
        """
        Concatenate the first sentence from each of the first 3 posts,
        separated by " | ".
        """
        snippets: list[str] = []
        for content in contents[:3]:
            if not content:
                continue
            for delim in (". ", ".\n", "\n"):
                if delim in content:
                    snippet = content.split(delim)[0].strip()
                    if len(snippet) > 20:
                        snippets.append(snippet[:200])
                        break
            else:
                snippets.append(content[:200])

        return " | ".join(snippets)


# Singleton
narrative_engine = NarrativeEngine()
