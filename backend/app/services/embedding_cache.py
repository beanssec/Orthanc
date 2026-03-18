"""In-memory LRU cache for embedding vectors.

Avoids redundant API calls for identical text+model combinations.
Thread-safe via asyncio (single-threaded event loop assumption).
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("orthanc.embedding_cache")


class EmbeddingCache:
    """LRU cache for embedding vectors.

    Key: MD5(text + model_id)
    Value: list[float] embedding vector
    Max size: configurable (default 10,000 entries)
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits: int = 0
        self._misses: int = 0

    @staticmethod
    def _make_key(text: str, model_id: str) -> str:
        """Generate a stable cache key from text and model_id."""
        payload = f"{model_id}:{text}"
        return hashlib.md5(payload.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str, model_id: str) -> Optional[list[float]]:
        """Look up an embedding. Returns None on cache miss."""
        key = self._make_key(text, model_id)
        value = self._cache.get(key)
        if value is not None:
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value
        self._misses += 1
        return None

    def put(self, text: str, model_id: str, embedding: list[float]) -> None:
        """Store an embedding. Evicts the LRU entry if at capacity."""
        if not embedding:
            return
        key = self._make_key(text, model_id)
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = embedding
            return
        # Evict LRU entry if at capacity
        if len(self._cache) >= self._max_size:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug("EmbeddingCache evicted key=%s (capacity=%d)", evicted_key[:8], self._max_size)
        self._cache[key] = embedding

    def stats(self) -> dict:
        """Return hit/miss counters and current size."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }

    def clear(self) -> None:
        """Clear all cached entries and reset counters."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0


# Module-level singleton
embedding_cache = EmbeddingCache(max_size=10_000)
