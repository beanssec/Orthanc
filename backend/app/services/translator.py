"""Translation service — uses available AI model credentials to translate text."""
from __future__ import annotations

import logging
import re
import unicodedata

from app.services.model_router import model_router

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

        try:
            api_result = await model_router.chat(
                task="translation",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            translated = api_result["content"].strip()
            return {
                "original": text,
                "translated": translated,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "model_used": api_result.get("model", "unknown"),
            }
        except Exception as exc:
            logger.warning("Translation via model_router failed: %s", exc)
            return {
                "original": text,
                "translated": None,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "error": "No AI credentials configured. Add xAI or OpenRouter credentials to use translation.",
            }




# Module-level singleton
translator = Translator()
