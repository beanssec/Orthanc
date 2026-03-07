"""Text embedding service for narrative clustering."""
import hashlib
import logging
import math
import struct
from typing import Optional

import httpx

logger = logging.getLogger("orthanc.embedding")


class EmbeddingService:
    def __init__(self):
        self._openrouter_key: Optional[str] = None

    def set_api_key(self, key: str):
        """Set OpenRouter API key for embedding API."""
        self._openrouter_key = key

    async def embed_text(self, text: str) -> list[float]:
        """Get embedding vector for text. Tries OpenRouter first, falls back to hash-based."""
        if self._openrouter_key:
            return await self._embed_openrouter(text)
        return self._embed_hash(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed multiple texts."""
        if self._openrouter_key:
            return await self._embed_openrouter_batch(texts)
        return [self._embed_hash(t) for t in texts]

    async def _embed_openrouter(self, text: str) -> list[float]:
        """Embed via OpenRouter API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={"Authorization": f"Bearer {self._openrouter_key}"},
                json={"model": "openai/text-embedding-3-small", "input": text[:8000]},
            )
            if resp.status_code != 200:
                logger.warning(
                    "OpenRouter embedding failed (%d), falling back to hash-based",
                    resp.status_code,
                )
                return self._embed_hash(text)
            data = resp.json()
            return data["data"][0]["embedding"]

    async def _embed_openrouter_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed via OpenRouter."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/embeddings",
                    headers={"Authorization": f"Bearer {self._openrouter_key}"},
                    json={
                        "model": "openai/text-embedding-3-small",
                        "input": [t[:8000] for t in texts],
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        "OpenRouter batch embedding failed (%d), falling back to hash-based",
                        resp.status_code,
                    )
                    return [self._embed_hash(t) for t in texts]
                data = resp.json()
                return [d["embedding"] for d in data["data"]]
        except Exception as e:
            logger.warning("Batch embedding failed: %s, using hash-based fallback", e)
            return [self._embed_hash(t) for t in texts]

    def _embed_hash(self, text: str) -> list[float]:
        """
        Fallback: deterministic 128-dim hash-based embedding.

        No external API or fitted model required. Words are hashed via MD5
        and projected into 128 dimensions. The result is L2-normalised so
        cosine similarity is equivalent to dot-product.
        """
        words = text.lower().split()[:200]

        dim = 128
        vec = [0.0] * dim

        for word in words:
            h = hashlib.md5(word.encode()).digest()
            for i in range(0, min(len(h), dim * 4), 4):
                val = struct.unpack("<f", h[i : i + 4])[0]
                # Filter out NaN/Inf from arbitrary byte interpretation
                if not math.isfinite(val):
                    val = 0.0
                idx = (i // 4) % dim
                vec[idx] += val

        # L2-normalise
        magnitude = sum(v * v for v in vec) ** 0.5
        if magnitude > 0:
            vec = [v / magnitude for v in vec]

        return vec


# Singleton used throughout the codebase
embedding_service = EmbeddingService()
