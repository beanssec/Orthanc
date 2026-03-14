"""Narrative clustering engine — groups posts about the same real-world events."""
import asyncio
import json
import logging
import math
import re
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

        # 3. Fall back to weighted top terms
        top = scored.most_common(8)
        if not top:
            return "Unclassified Event"

        # Prefer action/location words in the title
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
    _LLM_TIMEOUT_SECONDS = 30

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
