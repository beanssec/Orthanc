"""Text embedding service for narrative clustering."""
import hashlib
import logging
import math
import struct

from app.services.model_router import model_router

logger = logging.getLogger("orthanc.embedding")


class EmbeddingService:
    def __init__(self):
        pass

    async def embed_text(self, text: str) -> list[float]:
        """Get embedding vector for text. Tries model_router first, falls back to hash-based."""
        try:
            vector = await model_router.embed(text)
            if vector:
                return vector
        except Exception as e:
            logger.warning("model_router embed failed, falling back to hash-based: %s", e)
        return self._embed_hash(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed multiple texts."""
        results = []
        for text in texts:
            results.append(await self.embed_text(text))
        return results

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
