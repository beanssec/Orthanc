"""Entity extraction service — NER via spaCy."""
from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("orthanc.entity_extractor")

# Dedicated thread pool for CPU-bound spaCy work so we don't block the event loop
_spacy_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spacy")

_TITLE_RE = re.compile(
    r"^(Mr|Mrs|Ms|Dr|Prof|President|PM|Sen|Rep|Gen|Adm|Col|Cpt|Lt|Sgt)\.?\s+",
    re.IGNORECASE,
)


class EntityExtractor:
    """Extracts named entities and normalizes them for linking."""

    def __init__(self) -> None:
        self._nlp = None

    def _load_model(self) -> None:
        """Lazy-load spaCy model on first use."""
        if self._nlp is None:
            import spacy  # noqa: PLC0415
            logger.info("Loading spaCy model for entity extraction …")
            self._nlp = spacy.load("en_core_web_sm")
            logger.info("spaCy model loaded for entity extraction.")

    def extract_entities(self, text: str) -> list[dict]:
        """Extract PERSON, ORG, GPE, EVENT, NORP entities from text.

        Returns a list of dicts: [{name, type, context_snippet}]
        """
        if not text or len(text.strip()) < 2:
            return []

        # Truncate very long texts to avoid CPU-bound spaCy blocking
        if len(text) > 5000:
            text = text[:5000]

        self._load_model()
        try:
            doc = self._nlp(text)
        except Exception as exc:
            logger.warning("spaCy processing failed: %s", exc)
            return []

        entities: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for ent in doc.ents:
            if ent.label_ not in ("PERSON", "ORG", "GPE", "EVENT", "NORP"):
                continue
            name = ent.text.strip()
            if len(name) <= 1:
                continue
            key = (name, ent.label_)
            if key in seen:
                continue
            seen.add(key)

            # Extract surrounding context (50 chars each side)
            start = max(0, ent.start_char - 50)
            end = min(len(text), ent.end_char + 50)
            context = text[start:end]

            entities.append({
                "name": name,
                "type": ent.label_,
                "context_snippet": context,
            })

        return entities

    async def extract_entities_async(self, text: str) -> list[dict]:
        """Non-blocking wrapper — runs spaCy NER in a thread pool.
        
        Always use this from async code (collectors, routers) to avoid
        blocking the event loop during CPU-bound NLP processing.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_spacy_executor, self.extract_entities, text)

    def canonical_name(self, name: str) -> str:
        """Normalize entity name for deduplication/linking.

        Strips titles, lowercases, and strips whitespace.
        """
        n = name.strip()
        n = _TITLE_RE.sub("", n)
        return n.lower().strip()


# Module-level singleton — shared across all collectors
entity_extractor = EntityExtractor()
