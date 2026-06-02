"""Entity extraction service — NER via LLM."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from .entity_aliases import ALIAS_LOOKUP

logger = logging.getLogger("orthanc.entity_extractor")

_TITLE_RE = re.compile(
    r"^(Mr|Mrs|Ms|Dr|Prof|President|PM|Sen|Rep|Gen|Adm|Col|Cpt|Lt|Sgt)\.?\s+",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_MULTI_SPACE_RE = re.compile(r"\s+")

# Pre-cleaning patterns
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_BARE_URL_RE = re.compile(r"(?:https?://|t\.me/)\S+")
_HANDLE_RE = re.compile(r"@\w+")
_POV_PREFIX_RE = re.compile(r"^(?:RU|UA|CIV|Drone)\s+POV:\s*", re.MULTILINE)
_ORIGINAL_MSG_RE = re.compile(r"^Original msg.*$", re.MULTILINE)
# Emoji pattern — matches Unicode emoji ranges including flags
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U0001F300-\U0001F5FF"  # misc symbols
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # Geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-C
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols and pictographs extended-A
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

_SYSTEM_PROMPT = (
    "You are an OSINT entity extraction system. Extract named entities from intelligence reports. "
    "Output ONLY a JSON array."
)

_USER_PROMPT_TEMPLATE = """Extract up to 10 named entities from this text. Only the most important.

Types: PERSON, ORG, GPE, NORP, MILITARY_UNIT, WEAPON_SYSTEM, EVENT
Do NOT extract: usernames, URLs, hashtags, channel names, emoji, metadata.
Transliterate non-English names to English.
Output ONLY a JSON array, nothing else.

Format: [{{"name":"...","type":"..."}}]

Text:
{text}"""

_VALID_TYPES = {"PERSON", "ORG", "GPE", "NORP", "MILITARY_UNIT", "WEAPON_SYSTEM", "EVENT"}


def _clean_text(text: str) -> str:
    """Pre-clean text before sending to LLM."""
    # Strip markdown links: [text](url) → text
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    # Remove bare URLs
    text = _BARE_URL_RE.sub("", text)
    # Remove @handles
    text = _HANDLE_RE.sub("", text)
    # Remove emoji
    text = _EMOJI_RE.sub("", text)
    # Remove POV prefixes
    text = _POV_PREFIX_RE.sub("", text)
    # Strip "Original msg" boilerplate lines
    text = _ORIGINAL_MSG_RE.sub("", text)
    # Collapse extra whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _regex_fallback(text: str) -> list[dict]:
    """Minimal regex-based extraction when LLM is unavailable.
    
    Looks for capitalized multi-word sequences that are likely named entities.
    Not as good as LLM extraction, but better than nothing.
    """
    # Very conservative: only extract obvious 2+ word proper noun sequences
    pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
    seen: set[str] = set()
    entities: list[dict] = []
    for m in pattern.finditer(text):
        name = m.group(1).strip()
        if name in seen or len(name) <= 2:
            continue
        # Skip common false positives
        if name.lower() in ("original msg",):
            continue
        seen.add(name)
        start = max(0, m.start() - 50)
        end = min(len(text), m.end() + 50)
        entities.append({
            "name": name,
            "type": "ORG",  # conservative default
            "context_snippet": text[start:end],
        })
        if len(entities) >= 10:
            break
    return entities


class EntityExtractor:
    """Extracts named entities and normalizes them for linking via LLM."""

    def extract_entities(self, text: str) -> list[dict]:
        """Synchronous wrapper — runs the async version in a new event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context — can't use run() directly
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self.extract_entities_async(text))
                    return future.result(timeout=35)
            else:
                return loop.run_until_complete(self.extract_entities_async(text))
        except Exception as exc:
            logger.warning("extract_entities sync wrapper failed: %s", exc)
            return []

    async def extract_entities_async(self, text: str) -> list[dict]:
        """Extract entities from text using LLM.
        
        1. Pre-clean the input text
        2. Call model router with TASK_ENTITY_EXTRACTION
        3. Parse JSON response
        4. Fall back to regex extraction if LLM fails
        """
        if not text or len(text.strip()) < 2:
            return []

        # Pre-clean the text
        cleaned = _clean_text(text)
        if not cleaned or len(cleaned.strip()) < 2:
            return []

        # Truncate very long texts
        if len(cleaned) > 5000:
            cleaned = cleaned[:5000]

        # Attempt LLM extraction
        try:
            from app.services.model_router import model_router, ModelRouter  # noqa: PLC0415

            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(text=cleaned)},
            ]

            result = await asyncio.wait_for(
                model_router.chat(
                    ModelRouter.TASK_ENTITY_EXTRACTION,
                    messages,
                    max_tokens=300,
                ),
                timeout=30.0,
            )

            content = result.get("content", "").strip()
            if not content:
                logger.debug("LLM returned empty content for entity extraction")
                return _regex_fallback(cleaned)

            # Parse JSON — strip markdown code fences if present
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            # The response_format=json_object sometimes returns {"entities": [...]}
            # rather than a bare array; handle both.
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                # Find the first list value (e.g. {"entities": [...]})
                found_list = False
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        found_list = True
                        break
                if not found_list:
                    # Single entity returned as a dict — wrap it
                    if "name" in parsed and "type" in parsed:
                        parsed = [parsed]
                    else:
                        logger.warning("LLM entity response is a dict with no list values: %s", content[:200])
                        return _regex_fallback(cleaned)

            if not isinstance(parsed, list):
                logger.warning("LLM entity response is not a list: %s", type(parsed))
                return _regex_fallback(cleaned)

            entities: list[dict] = []
            seen: set[tuple[str, str]] = set()

            for item in parsed:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                entity_type = item.get("type", "").strip().upper()

                if not name or len(name) <= 1:
                    continue
                if entity_type not in _VALID_TYPES:
                    # Try to recover — treat unknown types as ORG
                    logger.debug("Unknown entity type '%s' for '%s', defaulting to ORG", entity_type, name)
                    entity_type = "ORG"

                key = (name.lower(), entity_type)
                if key in seen:
                    continue
                seen.add(key)

                entities.append({
                    "name": name,
                    "type": entity_type,
                    "context_snippet": item.get("context_snippet", "")[:200],
                })

            logger.debug("LLM extracted %d entities from text (len=%d)", len(entities), len(cleaned))
            return entities

        except asyncio.TimeoutError:
            logger.warning("LLM entity extraction timed out after 30s, falling back to regex")
            return _regex_fallback(cleaned)
        except Exception as exc:
            logger.warning("LLM entity extraction failed (%s), falling back to regex", exc)
            return _regex_fallback(cleaned)

    def canonical_name(self, name: str) -> str:
        """Normalize entity name for deduplication/linking.

        Pipeline:
        1. Strip leading honorific titles (Mr., Dr., Gen., etc.)
        2. Lowercase
        3. Replace all non-alphanumeric chars with spaces
           (handles dots in U.S.A., I.R.G.C., hyphens in al-Qaeda, etc.)
        4. Collapse multiple spaces
        5. Look up in ALIAS_LOOKUP — covers country abbreviations (US/UK/UAE),
           org acronyms (NATO/IRGC/IDF/CIA/…), and common variants.
           If no alias matches the normalized form is returned as-is.
        """
        n = name.strip()
        n = _TITLE_RE.sub("", n)
        n = n.lower().strip()
        n = _NON_ALNUM_RE.sub(" ", n)
        n = _MULTI_SPACE_RE.sub(" ", n).strip()
        return ALIAS_LOOKUP.get(n, n)


# Module-level singleton — shared across all collectors
entity_extractor = EntityExtractor()
