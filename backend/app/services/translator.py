"""Translation service — uses available AI model credentials to translate text."""
from __future__ import annotations

import logging
import re
import unicodedata

import httpx

from app.services.collector_manager import collector_manager

logger = logging.getLogger("orthanc.services.translator")

# Language detection character set ranges
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
FARSI_SPECIFIC = re.compile(r"[\u06C0-\u06D3\u06F0-\u06FF\u0750-\u077F]")
CHINESE_RE = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF\u20000-\u2A6DF]")
KOREAN_RE = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF]")
HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
LATIN_RE = re.compile(r"[a-zA-Z]")

LANG_NAMES = {
    "ru": "Russian",
    "ar": "Arabic",
    "fa": "Farsi (Persian)",
    "zh": "Chinese",
    "ko": "Korean",
    "he": "Hebrew",
    "uk": "Ukrainian",
    "en": "English",
}


class Translator:
    """Translates text using user-configured AI model credentials."""

    async def detect_language(self, text: str) -> str:
        """
        Heuristic language detection based on character sets.
        Returns ISO 639-1 language code.
        """
        if not text or not text.strip():
            return "en"

        # Count character types
        cyrillic_count = len(CYRILLIC_RE.findall(text))
        arabic_count = len(ARABIC_RE.findall(text))
        farsi_count = len(FARSI_SPECIFIC.findall(text))
        chinese_count = len(CHINESE_RE.findall(text))
        korean_count = len(KOREAN_RE.findall(text))
        hebrew_count = len(HEBREW_RE.findall(text))
        total = max(len(text.strip()), 1)

        # Threshold: 10% of chars in a script → that language
        if cyrillic_count / total > 0.10:
            # Distinguish Ukrainian from Russian (rough heuristic)
            # Ukrainian-specific letters: і, ї, є, ґ
            ua_specific = len(re.findall(r"[іїєґІЇЄҐ]", text))
            if ua_specific > 2:
                return "uk"
            return "ru"

        if arabic_count / total > 0.10:
            if farsi_count > 3:
                return "fa"
            return "ar"

        if chinese_count / total > 0.10:
            return "zh"

        if korean_count / total > 0.10:
            return "ko"

        if hebrew_count / total > 0.10:
            return "he"

        return "en"

    async def translate(
        self,
        text: str,
        target_lang: str,
        user_id: str,
    ) -> dict:
        """
        Translate text to target_lang using user's AI credentials.
        Tries xAI (Grok) first, then OpenRouter.

        Returns:
            {"original": str, "translated": str, "source_lang": str, "target_lang": str}
        """
        source_lang = await self.detect_language(text)

        if source_lang == target_lang or (source_lang == "en" and target_lang == "en"):
            return {
                "original": text,
                "translated": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "no_translation_needed": True,
            }

        lang_name = LANG_NAMES.get(target_lang, target_lang)
        system_prompt = (
            f"Translate the following text to {lang_name}. "
            "Return ONLY the translation, nothing else. "
            "Preserve proper nouns, place names, and military terminology as appropriate."
        )

        # Try xAI first
        x_keys = await collector_manager.get_keys(user_id, "x")
        if x_keys and x_keys.get("api_key"):
            result = await self._call_xai(
                api_key=x_keys["api_key"],
                system_prompt=system_prompt,
                text=text,
            )
            if result:
                return {
                    "original": text,
                    "translated": result,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "model_used": "grok-3-mini",
                }

        # Fall back to OpenRouter
        or_keys = await collector_manager.get_keys(user_id, "openrouter")
        if or_keys and or_keys.get("api_key"):
            result = await self._call_openrouter(
                api_key=or_keys["api_key"],
                system_prompt=system_prompt,
                text=text,
            )
            if result:
                return {
                    "original": text,
                    "translated": result,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "model_used": "openrouter",
                }

        return {
            "original": text,
            "translated": None,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "error": "No AI credentials configured. Add xAI or OpenRouter credentials to use translation.",
        }

    async def _call_xai(
        self, api_key: str, system_prompt: str, text: str
    ) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "grok-3-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 2000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            logger.warning("xAI translation failed: %s", exc)
            return None

    async def _call_openrouter(
        self, api_key: str, system_prompt: str, text: str
    ) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://orthanc.local",
                        "X-Title": "Orthanc OSINT",
                    },
                    json={
                        "model": "meta-llama/llama-3.3-70b-instruct",  # free tier
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 2000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            logger.warning("OpenRouter translation failed: %s", exc)
            return None


# Module-level singleton
translator = Translator()
