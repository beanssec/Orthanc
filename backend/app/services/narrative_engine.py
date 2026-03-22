"""Narrative clustering engine — groups posts about the same real-world events."""
import asyncio
import json
import logging
import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, update

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.narrative import Narrative, NarrativePost, PostEmbedding
from app.models.post import Post
from app.services.embedding_service import embedding_service

logger = logging.getLogger("orthanc.narrative")

# ──────────────────────────────────────────────
# Stale-lock helpers (file-based, timestamp TTL)
# ──────────────────────────────────────────────

_LOCK_FILE = "/tmp/orthanc_narrative_engine.lock"
_LOCK_TTL_SECONDS = 300  # 5 minutes


def _clear_stale_lock() -> None:
    """Remove the lock file if it is absent or older than _LOCK_TTL_SECONDS."""
    if not os.path.exists(_LOCK_FILE):
        return
    try:
        with open(_LOCK_FILE) as f:
            lock_ts = float(f.read().strip())
        age = time.time() - lock_ts
        if age > _LOCK_TTL_SECONDS:
            os.remove(_LOCK_FILE)
            logger.info(
                "Narrative engine: cleared stale lock (age=%.0fs, TTL=%ds)",
                age, _LOCK_TTL_SECONDS,
            )
    except Exception:
        # Corrupt / unreadable lock — remove it
        try:
            os.remove(_LOCK_FILE)
        except OSError:
            pass


def _write_lock() -> None:
    """Write (or refresh) the lock file with the current timestamp."""
    try:
        with open(_LOCK_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError as exc:
        logger.warning("Narrative engine: could not write lock file: %s", exc)


def _release_lock() -> None:
    """Delete the lock file on clean shutdown."""
    try:
        if os.path.exists(_LOCK_FILE):
            os.remove(_LOCK_FILE)
    except OSError:
        pass

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
# Stop-words — general + source-attribution boilerplate
# ──────────────────────────────────────────────

_STOP_WORDS = frozenset({
    # articles / prepositions / conjunctions
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
    # source-attribution / boilerplate noise
    "according", "https", "http", "www", "com", "rt", "via",
    "official", "officials", "embassy",
    "report", "reports", "reported", "reportedly",
    "statement", "statements",
    "media", "source", "sources",
    "claim", "claims",
    "breaking", "told", "tell", "telling", "saying",
    "news", "alert", "update", "updates",
    "reuters", "ap", "afp", "cnn", "bbc", "aljazeera", "rferl",
    "press", "correspondent", "journalist", "editor",
    "tweet", "tweets", "post", "posts",
    "thread", "threads", "share", "shared",
    "read", "click", "link", "links", "here", "watch",
    "pic", "photo", "photo1", "photo2", "image",
    "video", "footage", "file", "files",
    "per", "amid", "amid", "amid",
    "amid", "following", "including", "regarding", "related",
    "today", "yesterday", "week", "month", "year",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
})

# Words stripped but preserved for weighting — do NOT add to stop-words
_ACTION_WORDS = frozenset({
    "strike", "strikes", "struck", "attack", "attacks", "attacked",
    "deploy", "deployed", "deploys", "launch", "launches", "launched",
    "warn", "warns", "warned", "warning",
    "evacuate", "evacuates", "evacuated", "evacuation",
    "sanction", "sanctions", "sanctioned",
    "accuse", "accuses", "accused",
    "confirm", "confirms", "confirmed",
    "deny", "denies", "denied",
    "advance", "advances", "advancing",
    "capture", "captures", "captured",
    "invade", "invades", "invaded", "invasion",
    "withdraw", "withdraws", "withdrawal",
    "ceasefire", "cease-fire",
    "negotiate", "negotiates", "negotiated", "negotiations",
    "impose", "imposes", "imposed",
    "threaten", "threatens", "threatened",
    "escalate", "escalates", "escalation",
    "retaliate", "retaliates", "retaliation",
    "liberate", "liberation",
    "blockade", "siege",
    "collapse", "collapses",
    "shoot", "shoots", "shooting",
    "kill", "kills", "killed",
    "wound", "wounds", "wounded",
    "arrest", "arrests", "arrested",
    "protest", "protests",
    "resign", "resigns", "resignation",
    "vote", "votes", "election",
})

_LOCATION_WORDS = frozenset({
    # countries
    "iran", "russia", "ukraine", "israel", "gaza", "syria", "iraq", "yemen",
    "china", "taiwan", "korea", "japan", "india", "pakistan", "turkey",
    "france", "germany", "britain", "uk", "usa", "america", "europe",
    "nato", "eu", "africa", "sudan", "ethiopia", "somalia", "libya",
    "azerbaijan", "armenia", "georgia", "moldova", "belarus", "poland",
    "serbia", "kosovo", "palestine", "lebanon", "jordan", "egypt", "saudi",
    "arabia", "qatar", "uae", "myanmar", "venezuela", "colombia",
    # cities / regions
    "tehran", "moscow", "washington", "kyiv", "kiev", "jerusalem", "tel-aviv",
    "beijing", "taipei", "pyongyang", "kabul", "baghdad", "damascus",
    "aleppo", "donbas", "zaporizhzhia", "kherson", "crimea",
    "red sea", "black sea", "mediterranean", "gulf", "strait",
    "donbass", "mariupol", "bakhmut", "kharkiv", "odessa",
    # multi-word handled via unigram
    "crimea", "balkans", "caucasus", "sahel", "sinai",
})

# ──────────────────────────────────────────────
# Narrative type keyword maps (order matters — first match wins)
# ──────────────────────────────────────────────

_TYPE_KEYWORDS: list[tuple[str, frozenset]] = [
    ("military", frozenset({
        "strike", "strikes", "attack", "attacks", "troops", "military",
        "war", "battle", "weapons", "drone", "drones", "missile", "missiles",
        "bomb", "bombs", "bombing", "tank", "tanks", "soldiers", "army",
        "navy", "airforce", "airstrike", "artillery", "shelling", "siege",
        "ceasefire", "frontline", "casualties", "killed", "wounded",
        "invasion", "invade", "captured", "liberated", "advance",
        "withdrawal", "evacuate", "evacuation", "blockade",
    })),
    ("sanctions", frozenset({
        "sanctions", "sanctioned", "sanction", "embargo", "asset freeze",
        "blacklist", "blacklisted", "ofac", "export controls", "ban",
        "restricted", "debarred",
    })),
    ("diplomatic", frozenset({
        "talks", "agreement", "treaty", "meeting", "summit", "envoy",
        "diplomat", "diplomatic", "negotiations", "negotiate", "deal",
        "accord", "bilateral", "multilateral", "foreign minister", "secretary",
        "ambassador", "visit", "delegation",
    })),
    ("economic", frozenset({
        "oil", "gas", "trade", "market", "markets", "inflation", "economy",
        "economic", "gdp", "tariff", "tariffs", "export", "import",
        "currency", "bank", "banking", "financial", "investment",
        "energy", "pipeline", "supply chain",
    })),
    ("policy", frozenset({
        "election", "elections", "vote", "votes", "parliament", "government",
        "legislation", "law", "reform", "policy", "ruling", "court",
        "constitution", "referendum", "protest", "protests", "opposition",
        "president", "prime minister", "minister", "cabinet",
    })),
    ("rumor", frozenset({
        "alleged", "allegedly", "unverified", "rumored", "rumour",
        "speculated", "speculation", "claim", "claims", "unconfirmed",
        "suggests", "possibly", "reportedly", "potential",
    })),
]


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
    STALE_HOURS = 12                # legacy: used only as fallback if TTL config not available
    LOOKBACK_HOURS = 72             # consider posts from last 3 days (catches missed cycles/restarts)
    POLL_INTERVAL = 600             # seconds between full cycles (10 min)
    MAX_POSTS_PER_CYCLE = 500       # max posts to embed in one cycle
    STARTUP_DELAY = 120             # seconds to wait before first cycle (allows providers to register via login)

    @property
    def _stale_ttl_hours(self) -> int:
        """Configurable TTL for stale narratives (default 48h, from NARRATIVE_STALE_TTL_HOURS)."""
        return getattr(settings, "NARRATIVE_STALE_TTL_HOURS", 48)

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        # Clear any stale lock from a previous crashed run before starting
        _clear_stale_lock()
        self._running = True
        _write_lock()
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
        _release_lock()
        logger.info("Narrative clustering engine stopped")

    # ──────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────

    async def _loop(self) -> None:
        # Delay first cycle to allow embedding providers to be registered via user login.
        # Without this, the engine attempts embed() immediately at startup before any
        # provider credentials are decrypted, producing empty vectors and log errors.
        logger.info(
            "Narrative engine: waiting %ds before first cycle (provider registration delay)",
            self.STARTUP_DELAY,
        )
        await asyncio.sleep(self.STARTUP_DELAY)
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:
                logger.exception("Narrative engine cycle error: %s", exc)
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _cycle(self) -> None:
        """One full clustering cycle."""
        # Refresh the lock timestamp so it doesn't expire mid-run
        _write_lock()
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
        await self._detect_narrative_duplicates()
        await self._extract_narrative_claims()
        await self._classify_narrative_evidence()

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

            # ── Generate all canonical label fields ──────────────────────
            labels = self._generate_labels(
                contents=contents,
                post_count=len(post_ids),
                source_count=len(source_types),
            )

            summary = self._generate_summary(contents)
            first_seen = min(timestamps) if timestamps else datetime.now(timezone.utc)

            async with AsyncSessionLocal() as session:
                narrative = Narrative(
                    # Legacy compatibility
                    title=labels["canonical_title"],
                    summary=summary,
                    status="active",
                    first_seen=first_seen,
                    last_updated=datetime.now(timezone.utc),
                    post_count=len(post_ids),
                    source_count=len(source_types),
                    # Canonical intelligence fields
                    raw_title=labels["raw_title"],
                    canonical_title=labels["canonical_title"],
                    canonical_claim=labels["canonical_claim"],
                    narrative_type=labels["narrative_type"],
                    label_confidence=labels["label_confidence"],
                    confirmation_status=labels["confirmation_status"],
                )
                session.add(narrative)
                await session.flush()  # populate narrative.id

                for pid in post_ids:
                    session.add(NarrativePost(narrative_id=narrative.id, post_id=pid))

                await session.commit()

            # ── LLM label refinement (Checkpoint 3) ──────────────────────
            # Run outside the create-transaction so a failure never blocks persistence.
            narrative_id_for_llm = narrative.id
            try:
                llm_refinements = await self._llm_label_narrative(
                    narrative_id=narrative_id_for_llm,
                    contents=contents,
                    heuristic_labels=labels,
                )
            except Exception as llm_exc:
                logger.warning(
                    "LLM label hook raised unexpectedly for narrative %s: %s — "
                    "heuristic labels retained",
                    narrative_id_for_llm, llm_exc,
                )
                llm_refinements = None

            if llm_refinements:
                # Merge only valid fields; heuristic values remain for anything not returned
                merged_labels = {**labels, **llm_refinements}
                try:
                    async with AsyncSessionLocal() as session:
                        result_n = await session.get(Narrative, narrative_id_for_llm)
                        if result_n is not None:
                            if "canonical_title" in llm_refinements:
                                result_n.canonical_title = merged_labels["canonical_title"]
                                result_n.title = merged_labels["canonical_title"]  # legacy field
                            if "canonical_claim" in llm_refinements:
                                result_n.canonical_claim = merged_labels["canonical_claim"]
                            if "narrative_type" in llm_refinements:
                                result_n.narrative_type = merged_labels["narrative_type"]
                            if "label_confidence" in llm_refinements:
                                result_n.label_confidence = merged_labels["label_confidence"]
                            if "confirmation_status" in llm_refinements:
                                result_n.confirmation_status = merged_labels["confirmation_status"]
                            await session.commit()
                        labels = merged_labels  # use merged for the log line below
                except Exception as persist_exc:
                    logger.warning(
                        "Failed to persist LLM refinements for narrative %s: %s — "
                        "heuristic labels remain in DB",
                        narrative_id_for_llm, persist_exc,
                    )

            created += 1
            logger.info(
                "New narrative '%s' [%s, conf=%.2f, status=%s] — %d posts from %d source types",
                labels["canonical_title"],
                labels["narrative_type"] or "other",
                labels["label_confidence"],
                labels["confirmation_status"],
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
    # Step 4b — extract claims from narratives
    # ──────────────────────────────────────────

    _MIN_POSTS_FOR_CLAIM_EXTRACTION = 5

    async def _extract_narrative_claims(self) -> None:
        """For each active narrative with ≥5 posts and no claim yet, extract a claim via LLM."""
        from app.services.claim_extractor import claim_extractor  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Narrative).where(
                    Narrative.status == "active",
                    Narrative.claim_text.is_(None),
                    Narrative.post_count >= self._MIN_POSTS_FOR_CLAIM_EXTRACTION,
                )
            )
            narratives = result.scalars().all()

        for narr in narratives:
            try:
                # Check if this narrative matches any active tracker — log for traceability
                try:
                    from app.models.narrative import NarrativeTracker, NarrativeTrackerMatch  # noqa: PLC0415
                    async with AsyncSessionLocal() as session:
                        tracker_result = await session.execute(
                            select(NarrativeTracker.name)
                            .join(
                                NarrativeTrackerMatch,
                                NarrativeTrackerMatch.tracker_id == NarrativeTracker.id,
                            )
                            .where(
                                NarrativeTrackerMatch.narrative_id == narr.id,
                                NarrativeTracker.status == "active",
                            )
                            .limit(5)
                        )
                        matched_tracker_names = [row[0] for row in tracker_result.all()]
                    if matched_tracker_names:
                        logger.info(
                            "Claim extraction: narrative %s matches tracker(s): %s",
                            narr.id,
                            ", ".join(matched_tracker_names),
                        )
                except Exception as _tracker_err:
                    logger.debug(
                        "Claim extraction: tracker lookup failed for narrative %s (non-fatal): %s",
                        narr.id, _tracker_err,
                    )

                # Fetch post contents for this narrative
                async with AsyncSessionLocal() as session:
                    posts_result = await session.execute(
                        select(Post.content)
                        .join(NarrativePost, NarrativePost.post_id == Post.id)
                        .where(
                            NarrativePost.narrative_id == narr.id,
                            Post.content.isnot(None),
                        )
                        .limit(10)
                    )
                    post_contents = [row[0] for row in posts_result.all()]

                if not post_contents:
                    continue

                # Build a truncated summary string
                posts_summary = "\n".join(
                    f"- {c[:200]}" for c in post_contents if c
                )

                # Gather entity names from topic_keywords as a proxy
                entity_names: list[str] = list(narr.topic_keywords or [])[:10]

                canonical_title = narr.canonical_title or narr.title or ""

                extraction = await claim_extractor.extract_claim(
                    narrative_id=str(narr.id),
                    posts_summary=posts_summary,
                    entity_names=entity_names,
                    canonical_title=canonical_title,
                )

                if not extraction:
                    continue

                # Persist extracted claim
                async with AsyncSessionLocal() as session:
                    narr_obj = await session.get(Narrative, narr.id)
                    if narr_obj is None:
                        continue
                    narr_obj.claim_text = extraction["claim_text"]
                    narr_obj.claimant = extraction["claimant"]
                    narr_obj.claim_type = extraction["claim_type"]
                    narr_obj.claim_confidence = extraction["confidence"]
                    narr_obj.claim_extracted_at = datetime.now(timezone.utc)
                    await session.commit()

                logger.info(
                    "Narrative claim stored | narrative=%s type=%s claimant=%r text=%r",
                    narr.id,
                    extraction["claim_type"],
                    extraction["claimant"],
                    extraction["claim_text"][:80],
                )

            except Exception as exc:
                logger.warning(
                    "Claim extraction error for narrative %s: %s", narr.id, exc
                )

    # ──────────────────────────────────────────
    # Step 4c — classify evidence for claims
    # ──────────────────────────────────────────

    async def _classify_narrative_evidence(self) -> None:
        """For each active narrative that has a claim_text, classify unclassified posts."""
        from app.services.evidence_classifier import evidence_classifier  # noqa: PLC0415

        # Fetch active narratives that have a claim
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Narrative).where(
                    Narrative.status == "active",
                    Narrative.claim_text.isnot(None),
                )
            )
            narratives = result.scalars().all()

        for narr in narratives:
            try:
                # Fetch narrative_posts that haven't been evidence-classified yet
                async with AsyncSessionLocal() as session:
                    np_result = await session.execute(
                        select(NarrativePost.id, NarrativePost.post_id, Post.content)
                        .join(Post, Post.id == NarrativePost.post_id)
                        .where(
                            NarrativePost.narrative_id == narr.id,
                            NarrativePost.evidence_classified_at.is_(None),
                            Post.content.isnot(None),
                        )
                        .limit(100)
                    )
                    rows = np_result.all()

                if not rows:
                    continue  # All posts already classified

                posts_for_classifier = [
                    {"post_id": str(post_id), "content": content}
                    for _np_id, post_id, content in rows
                ]

                classifications = await evidence_classifier.classify_evidence(
                    claim_text=narr.claim_text,
                    claimant=narr.claimant or "",
                    posts=posts_for_classifier,
                )

                if not classifications:
                    continue

                # Build lookup: post_id → classification
                class_map = {c["post_id"]: c for c in classifications}

                # Persist results onto NarrativePost rows
                now = datetime.now(timezone.utc)
                counts: Counter = Counter()

                async with AsyncSessionLocal() as session:
                    for np_id, post_id, _content in rows:
                        c = class_map.get(str(post_id))
                        if c is None:
                            continue
                        np_obj = await session.get(NarrativePost, np_id)
                        if np_obj is None:
                            continue
                        np_obj.evidence_role = c["role"]
                        np_obj.evidence_confidence = c["confidence"]
                        np_obj.evidence_classified_at = now
                        counts[c["role"]] += 1
                    await session.commit()

                logger.info(
                    "Evidence classified | narrative=%s supports=%d contradicts=%d "
                    "contextual=%d unclear=%d",
                    narr.id,
                    counts.get("supports", 0),
                    counts.get("contradicts", 0),
                    counts.get("contextual", 0),
                    counts.get("unclear", 0),
                )

            except Exception as exc:
                logger.warning(
                    "Evidence classification error for narrative %s: %s", narr.id, exc
                )

    # ──────────────────────────────────────────
    # Step 5 — mark stale narratives
    # ──────────────────────────────────────────

    async def _mark_stale_narratives(self) -> None:
        """Demote active narratives that have had no new posts within NARRATIVE_STALE_TTL_HOURS.

        Narratives are marked 'stale' (status field) and a stale_at timestamp is set if the
        column exists. They are never deleted — just demoted for downstream filtering.
        """
        ttl_hours = self._stale_ttl_hours
        stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            # Build update values — include stale_at if the column exists on the model
            update_values: dict = {"status": "stale"}
            if hasattr(Narrative, "stale_at"):
                update_values["stale_at"] = now

            result = await session.execute(
                update(Narrative)
                .where(
                    Narrative.status == "active",
                    Narrative.last_updated < stale_cutoff,
                )
                .values(**update_values)
                .returning(Narrative.id)
            )
            staled_ids = result.fetchall()
            await session.commit()

        if staled_ids:
            logger.info(
                "Narrative engine: marked %d narrative(s) stale (TTL=%dh, cutoff=%s)",
                len(staled_ids),
                ttl_hours,
                stale_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

    # ──────────────────────────────────────────
    # Step 6 — detect duplicate / overlapping narratives
    # ──────────────────────────────────────────

    DUPLICATE_OVERLAP_THRESHOLD = 0.60  # >60% shared posts → candidate for merge

    async def _detect_narrative_duplicates(self) -> None:
        """
        Compare pairs of active narratives by post overlap.

        If two narratives share > DUPLICATE_OVERLAP_THRESHOLD of the *smaller*
        narrative's posts, the smaller one is marked as a merge candidate by
        setting merged_into → the larger narrative's id.

        No posts are moved and no narrative is deleted — this stores the match
        for admin review only.
        """
        async with AsyncSessionLocal() as session:
            # Fetch active narratives that aren't already merged
            result = await session.execute(
                select(Narrative.id, Narrative.post_count)
                .where(
                    Narrative.status == "active",
                    Narrative.merged_into.is_(None),
                    Narrative.post_count >= self.MIN_POSTS_FOR_NARRATIVE,
                )
                .order_by(Narrative.post_count.desc())
                .limit(100)
            )
            active = result.all()  # list of (id, post_count)

        if len(active) < 2:
            return

        # Build post-id sets per narrative
        narrative_post_sets: dict = {}
        for nid, _pc in active:
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(NarrativePost.post_id)
                    .where(NarrativePost.narrative_id == nid)
                )
                narrative_post_sets[nid] = set(r[0] for r in res.all())

        merged_this_cycle: set = set()

        for i, (nid_a, pc_a) in enumerate(active):
            if nid_a in merged_this_cycle:
                continue
            posts_a = narrative_post_sets.get(nid_a, set())
            if not posts_a:
                continue

            for nid_b, pc_b in active[i + 1:]:
                if nid_b in merged_this_cycle:
                    continue
                posts_b = narrative_post_sets.get(nid_b, set())
                if not posts_b:
                    continue

                # Compute overlap relative to the smaller narrative
                intersection = posts_a & posts_b
                if not intersection:
                    continue

                smaller_count = min(len(posts_a), len(posts_b))
                overlap_ratio = len(intersection) / smaller_count

                if overlap_ratio > self.DUPLICATE_OVERLAP_THRESHOLD:
                    # Smaller narrative is the duplicate; larger is canonical
                    canonical_id = nid_a if pc_a >= pc_b else nid_b
                    duplicate_id = nid_b if pc_a >= pc_b else nid_a

                    logger.info(
                        "Narrative duplicate detected: %s → canonical %s "
                        "(overlap=%.2f, shared=%d posts) — flagged for admin review",
                        duplicate_id, canonical_id, overlap_ratio, len(intersection),
                    )

                    async with AsyncSessionLocal() as session:
                        dup = await session.get(Narrative, duplicate_id)
                        if dup is not None and dup.merged_into is None:
                            dup.merged_into = canonical_id
                            dup.merge_candidate_score = round(overlap_ratio, 4)
                            await session.commit()

                    merged_this_cycle.add(duplicate_id)

    # ──────────────────────────────────────────
    # Canonical label generation — public entry point
    # ──────────────────────────────────────────

    def _generate_labels(
        self,
        contents: list[str],
        post_count: int,
        source_count: int,
    ) -> dict:
        """
        Compute all canonical label fields for a new (or refreshed) narrative.

        Returns a dict with keys:
          raw_title, canonical_title, canonical_claim,
          narrative_type, label_confidence, confirmation_status
        """
        raw_title = self._heuristic_raw_title(contents)
        canonical_title = self._heuristic_canonical_title(contents)
        canonical_claim = self._heuristic_canonical_claim(contents)
        narrative_type = self._assign_narrative_type(contents)
        label_confidence = self._compute_label_confidence(
            contents, post_count, source_count, narrative_type
        )
        confirmation_status = self._compute_confirmation_status(
            post_count, source_count, label_confidence
        )

        return {
            "raw_title": raw_title,
            "canonical_title": canonical_title,
            "canonical_claim": canonical_claim,
            "narrative_type": narrative_type,
            "label_confidence": label_confidence,
            "confirmation_status": confirmation_status,
        }

    # ──────────────────────────────────────────
    # Heuristic title helpers
    # ──────────────────────────────────────────

    def _heuristic_raw_title(self, contents: list[str]) -> str:
        """
        Naive bag-of-words title — the pre-canonical raw label.
        Preserved for audit trail / Checkpoint 3 comparison.
        """
        words: Counter = Counter()
        for content in contents[:10]:
            if not content:
                continue
            for raw in content.lower().split():
                word = re.sub(r"[^\w-]", "", raw)
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

    def _heuristic_canonical_title(self, contents: list[str]) -> str:
        """
        Weighted title: action and location words score higher.
        Also tries to find capitalized proper-noun runs in the source text.
        Produces a more analyst-usable display label.
        """
        # 1. Score lower-cased tokens with weights
        scored: Counter = Counter()
        proper_nouns: Counter = Counter()

        for content in contents[:15]:
            if not content:
                continue

            # Extract capitalized runs (likely proper nouns) from original text
            # Pattern: 2+ consecutive Title-Case words not at sentence start
            cap_runs = re.findall(
                r"(?<=[.!?\s])(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
                content,
            )
            for run in cap_runs:
                key = run.strip()
                if (
                    len(key) > 4
                    and not any(bw in key.lower().split() for bw in _STOP_WORDS)
                ):
                    proper_nouns[key] += 1

            # Weighted unigram scoring
            for raw in content.lower().split():
                word = re.sub(r"[^\w-]", "", raw)
                if not word or len(word) < 3 or word.startswith("http"):
                    continue
                if word in _STOP_WORDS:
                    continue
                if word in _ACTION_WORDS:
                    scored[word] += 3
                elif word in _LOCATION_WORDS:
                    scored[word] += 2
                else:
                    scored[word] += 1

        # 2. Prefer a prominent proper noun phrase if strongly recurring
        if proper_nouns:
            top_pn, top_pn_count = proper_nouns.most_common(1)[0]
            if top_pn_count >= 2:
                # Supplement with top action/location word
                action_loc = [
                    w for w, _ in scored.most_common(10)
                    if w in _ACTION_WORDS or w in _LOCATION_WORDS
                ]
                if action_loc:
                    candidate = f"{top_pn} — {action_loc[0].title()}"
                    if len(candidate) <= 80:
                        return candidate
                return top_pn

        # 3. Fall back to best representative sentence as title
        # Instead of keyword soup, find the most informative short sentence
        best_sentence = None
        best_score = -1
        for content in contents[:10]:
            if not content:
                continue
            # Only consider English-ish content for heuristic titles
            latin_ratio = len(re.findall(r"[a-zA-Z]", content)) / max(len(content), 1)
            if latin_ratio < 0.4:
                continue
            sentences = re.split(r"(?<=[.!?])\s+", content.strip())
            for sentence in sentences:
                s = sentence.strip()
                if len(s) < 20 or len(s) > 120:
                    continue
                # Score: prefer sentences with action words + proper nouns
                score = 0
                for w in s.lower().split():
                    w_clean = re.sub(r"[^\w-]", "", w)
                    if w_clean in _ACTION_WORDS:
                        score += 3
                    elif w_clean in _LOCATION_WORDS:
                        score += 2
                    elif w_clean and w_clean[0].isupper():
                        score += 1
                if score > best_score:
                    best_score = score
                    best_sentence = s

        if best_sentence:
            # Truncate to 80 chars
            if len(best_sentence) > 80:
                return best_sentence[:77] + "…"
            return best_sentence

        # Ultimate fallback to weighted top terms
        top = scored.most_common(8)
        if not top:
            return "Unclassified Event"

        priority = [w for w, _ in top if w in _ACTION_WORDS or w in _LOCATION_WORDS]
        others = [w for w, _ in top if w not in _ACTION_WORDS and w not in _LOCATION_WORDS]

        parts = priority[:2] + others[:2]
        if not parts:
            parts = [w for w, _ in top[:4]]

        return " ".join(w.title() for w in parts[:4])

    def _heuristic_canonical_claim(self, contents: list[str]) -> str:
        """
        Extract the single best representative sentence from the cluster
        as a canonical claim summary. Prefers sentences containing action
        words and location words. Falls back to _generate_summary style.
        """
        candidates: list[tuple[float, str]] = []

        for content in contents[:20]:
            if not content:
                continue
            # Split on sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", content.strip())
            for sentence in sentences:
                s = sentence.strip()
                if len(s) < 30 or len(s) > 300:
                    continue

                # Skip lines that look like pure boilerplate/attribution
                lower = s.lower()
                if any(b in lower for b in (
                    "breaking:", "rt @", "via @", "https://", "http://",
                    "follow us", "subscribe", "full story",
                )):
                    continue

                # Score sentence
                tokens = set(re.sub(r"[^\w ]", "", lower).split())
                score = 0.0
                score += sum(1.5 for t in tokens if t in _ACTION_WORDS)
                score += sum(1.2 for t in tokens if t in _LOCATION_WORDS)
                score += 0.5 if len(s) > 60 else 0.0  # slightly prefer longer sentences
                score -= sum(0.3 for t in tokens if t in _STOP_WORDS)

                candidates.append((score, s))

        if not candidates:
            return self._generate_summary(contents)

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1][:400]

    # ──────────────────────────────────────────
    # Narrative type classifier
    # ──────────────────────────────────────────

    def _assign_narrative_type(self, contents: list[str]) -> str:
        """
        Score each type bucket against the cluster text and return the
        highest-scoring type. Falls back to 'other'.
        """
        combined = " ".join(c.lower() for c in contents[:20] if c)
        tokens = set(re.sub(r"[^\w ]", " ", combined).split())

        scores: dict[str, int] = {}
        for type_name, keywords in _TYPE_KEYWORDS:
            scores[type_name] = len(tokens & keywords)

        best_type = max(scores, key=lambda k: scores[k])
        if scores[best_type] == 0:
            return "other"
        return best_type

    # ──────────────────────────────────────────
    # Confidence + confirmation heuristics
    # ──────────────────────────────────────────

    def _compute_label_confidence(
        self,
        contents: list[str],
        post_count: int,
        source_count: int,
        narrative_type: Optional[str],
    ) -> float:
        """
        Simple heuristic confidence score (0–1) for the label quality.

        Factors:
        - number of posts (more = more signal)
        - number of distinct sources (cross-source = stronger)
        - whether a non-'other' type was detected
        - average content length (longer posts = richer signal)
        """
        score = 0.0

        # Post count contribution (saturates at ~20)
        score += min(post_count / 20.0, 1.0) * 0.30

        # Source diversity contribution (saturates at ~5)
        score += min(source_count / 5.0, 1.0) * 0.30

        # Type detection bonus
        if narrative_type and narrative_type != "other":
            score += 0.20

        # Average content length (proxy for post richness)
        if contents:
            avg_len = sum(len(c) for c in contents[:10]) / min(len(contents), 10)
            score += min(avg_len / 500.0, 1.0) * 0.20

        return round(min(score, 1.0), 3)

    def _compute_confirmation_status(
        self,
        post_count: int,
        source_count: int,
        label_confidence: float,
    ) -> str:
        """
        Assign a heuristic confirmation status based on cluster strength.

        - 'heuristic'     : small/weak cluster, labels are rough estimates
        - 'weak_cluster'  : moderate cluster, label is reasonable
        - 'mixed_cluster' : multiple sources, higher confidence
        """
        if source_count >= 3 and post_count >= 8 and label_confidence >= 0.55:
            return "mixed_cluster"
        if source_count >= 2 and post_count >= 4 and label_confidence >= 0.35:
            return "weak_cluster"
        return "heuristic"

    # ──────────────────────────────────────────
    # LLM hook — Checkpoint 3 implementation
    # ──────────────────────────────────────────

    # Valid narrative types the LLM is allowed to return
    _VALID_NARRATIVE_TYPES = frozenset({
        "military", "sanctions", "diplomatic", "economic",
        "policy", "rumor", "other",
    })

    # Valid confirmation statuses the LLM is allowed to return
    _VALID_CONFIRMATION_STATUSES = frozenset({
        "llm_confirmed", "llm_mixed", "llm_weak",
        # heuristic values kept for backward compat
        "heuristic", "weak_cluster", "mixed_cluster",
    })

    # Hard cap on how many post snippets we send to the LLM (token hygiene)
    _LLM_MAX_SNIPPETS = 6
    _LLM_SNIPPET_CHARS = 300
    _LLM_TIMEOUT_SECONDS = 60

    async def _llm_label_narrative(
        self,
        narrative_id,
        contents: list[str],
        heuristic_labels: dict,
    ) -> Optional[dict]:
        """
        Model-router-assisted narrative labeling (Checkpoint 3).

        Calls model_router with TASK_NARRATIVE_LABEL to refine the heuristic
        labels, then optionally calls TASK_NARRATIVE_CONFIRMATION to improve
        confirmation_status.

        Returns a partial dict (only keys that the LLM successfully improved),
        or None if no provider is available or the call fails.
        Heuristic values are never replaced with invalid/malformed LLM output.
        """
        # Import here to avoid circular imports at module load time
        try:
            from app.services.model_router import model_router, ModelRouter  # noqa: PLC0415
        except ImportError as exc:
            logger.debug("model_router not importable — skipping LLM label hook: %s", exc)
            return None

        if not model_router._providers:
            logger.debug(
                "No LLM providers registered — skipping LLM label for narrative %s",
                narrative_id,
            )
            return None

        # Build post snippets (short, clean, bounded)
        snippets = []
        for c in contents[:self._LLM_MAX_SNIPPETS]:
            if c:
                snippet = c.strip()[: self._LLM_SNIPPET_CHARS]
                snippets.append(snippet)

        if not snippets:
            return None

        snippets_text = "\n---\n".join(f"[{i+1}] {s}" for i, s in enumerate(snippets))

        # ── Step 1: narrative_label refinement ──────────────────────────
        label_result = await self._call_llm_label(
            model_router=model_router,
            narrative_id=narrative_id,
            snippets_text=snippets_text,
            heuristic_labels=heuristic_labels,
        )

        # ── Step 2: narrative_confirmation ──────────────────────────────
        confirm_result = await self._call_llm_confirmation(
            model_router=model_router,
            narrative_id=narrative_id,
            snippets_text=snippets_text,
            heuristic_labels=heuristic_labels,
            label_result=label_result,
        )

        # Merge: start from label result, layer confirmation on top
        merged: dict = {}
        if label_result:
            merged.update(label_result)
        if confirm_result:
            merged.update(confirm_result)

        return merged if merged else None

    async def _call_llm_label(
        self,
        model_router,
        narrative_id,
        snippets_text: str,
        heuristic_labels: dict,
    ) -> Optional[dict]:
        """
        Call TASK_NARRATIVE_LABEL and parse structured JSON output.
        Returns a dict with refined label fields, or None on failure.
        """
        from app.services.model_router import ModelRouter  # noqa: PLC0415

        system_prompt = (
            "You are an expert OSINT analyst. You will be given a set of social-media posts "
            "about a real-world event, along with a draft heuristic label. "
            "Your job is to refine that label into a precise, analyst-grade intelligence label.\n\n"
            "Output ONLY a JSON object with these exact keys:\n"
            "  canonical_title  : short event title (≤12 words, proper nouns, no filler)\n"
            "  canonical_claim  : one declarative sentence summarising the core claim (≤50 words)\n"
            "  narrative_type   : one of: military, sanctions, diplomatic, economic, policy, rumor, other\n"
            "  label_confidence : float 0.0–1.0 reflecting your confidence in the label\n\n"
            "Do NOT wrap in markdown. Do NOT explain. Output raw JSON only."
        )

        user_prompt = (
            f"HEURISTIC LABELS (draft):\n"
            f"  title   : {heuristic_labels.get('canonical_title', '')}\n"
            f"  claim   : {heuristic_labels.get('canonical_claim', '')}\n"
            f"  type    : {heuristic_labels.get('narrative_type', '')}\n"
            f"  conf    : {heuristic_labels.get('label_confidence', '')}\n\n"
            f"POST SNIPPETS:\n{snippets_text}\n\n"
            "Return refined JSON label:"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await asyncio.wait_for(
                model_router.chat(ModelRouter.TASK_NARRATIVE_LABEL, messages),
                timeout=self._LLM_TIMEOUT_SECONDS,
            )
            raw_content = response.get("content", "").strip()
            parsed = self._safe_parse_label_json(raw_content, narrative_id)
            if parsed:
                logger.info(
                    "LLM narrative label refined | narrative=%s title=%r type=%s conf=%.2f",
                    narrative_id,
                    parsed.get("canonical_title", "?"),
                    parsed.get("narrative_type", "?"),
                    parsed.get("label_confidence", 0.0),
                )
            return parsed
        except asyncio.TimeoutError:
            logger.warning(
                "LLM narrative_label timed out after %ds for narrative %s — using heuristics",
                self._LLM_TIMEOUT_SECONDS, narrative_id,
            )
            return None
        except Exception as exc:
            logger.warning(
                "LLM narrative_label failed for narrative %s: %s — using heuristics",
                narrative_id, exc,
            )
            return None

    async def _call_llm_confirmation(
        self,
        model_router,
        narrative_id,
        snippets_text: str,
        heuristic_labels: dict,
        label_result: Optional[dict],
    ) -> Optional[dict]:
        """
        Call TASK_NARRATIVE_CONFIRMATION and parse the confirmation_status.
        Returns {"confirmation_status": str} or None on failure.
        """
        from app.services.model_router import ModelRouter  # noqa: PLC0415

        # Use refined title if available
        title = (label_result or {}).get(
            "canonical_title", heuristic_labels.get("canonical_title", "")
        )
        claim = (label_result or {}).get(
            "canonical_claim", heuristic_labels.get("canonical_claim", "")
        )

        system_prompt = (
            "You are an OSINT verification analyst. Given post snippets and an event label, "
            "assess whether the posts coherently confirm the same event narrative.\n\n"
            "Output ONLY a JSON object with these exact keys:\n"
            "  confirmation_status : one of: llm_confirmed, llm_mixed, llm_weak\n"
            "    llm_confirmed = posts clearly and consistently describe the same event\n"
            "    llm_mixed     = posts partially agree but contain contradictions or noise\n"
            "    llm_weak      = posts are ambiguous, sparse, or divergent\n\n"
            "Do NOT wrap in markdown. Output raw JSON only."
        )

        user_prompt = (
            f"EVENT LABEL:\n  title: {title}\n  claim: {claim}\n\n"
            f"POST SNIPPETS:\n{snippets_text}\n\n"
            "Return confirmation JSON:"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await asyncio.wait_for(
                model_router.chat(ModelRouter.TASK_NARRATIVE_CONFIRMATION, messages),
                timeout=self._LLM_TIMEOUT_SECONDS,
            )
            raw_content = response.get("content", "").strip()
            parsed = self._safe_parse_confirmation_json(raw_content, narrative_id)
            if parsed:
                logger.info(
                    "LLM narrative confirmation | narrative=%s status=%s",
                    narrative_id, parsed.get("confirmation_status", "?"),
                )
            return parsed
        except asyncio.TimeoutError:
            logger.warning(
                "LLM narrative_confirmation timed out for narrative %s — keeping heuristic status",
                narrative_id,
            )
            return None
        except Exception as exc:
            logger.warning(
                "LLM narrative_confirmation failed for narrative %s: %s — keeping heuristic status",
                narrative_id, exc,
            )
            return None

    def _safe_parse_label_json(self, raw: str, narrative_id) -> Optional[dict]:
        """
        Safely parse the LLM label response JSON.
        Only returns fields that pass basic validation; ignores invalid ones.
        Returns None if parsing fails entirely.
        """
        # Strip accidental markdown fences
        text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("LLM label JSON parse failed for narrative %s: %s | raw=%r", narrative_id, exc, raw[:200])
            return None

        if not isinstance(data, dict):
            return None

        refined: dict = {}

        # canonical_title — string, reasonable length
        ct = data.get("canonical_title")
        if isinstance(ct, str) and 3 <= len(ct.strip()) <= 120:
            refined["canonical_title"] = ct.strip()

        # canonical_claim — string, reasonable length
        cc = data.get("canonical_claim")
        if isinstance(cc, str) and 10 <= len(cc.strip()) <= 500:
            refined["canonical_claim"] = cc.strip()

        # narrative_type — must be in whitelist
        nt = data.get("narrative_type")
        if isinstance(nt, str) and nt.strip().lower() in self._VALID_NARRATIVE_TYPES:
            refined["narrative_type"] = nt.strip().lower()

        # label_confidence — float in [0, 1]
        lc = data.get("label_confidence")
        if isinstance(lc, (int, float)) and 0.0 <= float(lc) <= 1.0:
            refined["label_confidence"] = round(float(lc), 3)

        return refined if refined else None

    def _safe_parse_confirmation_json(self, raw: str, narrative_id) -> Optional[dict]:
        """
        Safely parse the LLM confirmation response JSON.
        Returns {"confirmation_status": str} or None.
        """
        text = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("LLM confirmation JSON parse failed for narrative %s: %s | raw=%r", narrative_id, exc, raw[:200])
            return None

        if not isinstance(data, dict):
            return None

        cs = data.get("confirmation_status")
        if isinstance(cs, str) and cs.strip().lower() in self._VALID_CONFIRMATION_STATUSES:
            return {"confirmation_status": cs.strip().lower()}

        return None

    # ──────────────────────────────────────────
    # Text utilities (legacy / shared)
    # ──────────────────────────────────────────

    def _generate_title(self, contents: list[str]) -> str:
        """
        Legacy compatibility shim.
        Now delegates to _heuristic_canonical_title.
        Kept for any external callers that referenced this method directly.
        """
        return self._heuristic_canonical_title(contents)

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
