"""Auto-translate non-English posts at ingestion time.

Runs as an async fire-and-forget task after post insertion.
Uses the translator service with Gemini Flash for speed/cost.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.services.translator import translator

logger = logging.getLogger("orthanc.auto_translator")

# Rate limiting — don't overwhelm the translation API
_semaphore = asyncio.Semaphore(3)  # max 3 concurrent translations


async def auto_translate_post(post_id: UUID, content: str, user_id: str) -> None:
    """Fire-and-forget: detect language and translate if non-English.

    Updates the post's detected_language, translated_content, and translation_model
    fields directly in the database.
    """
    if not content or len(content.strip()) < 10:
        return

    async with _semaphore:
        try:
            # Detect language
            lang = await translator.detect_language(content)

            if lang == "en":
                # Still record the detected language
                async with AsyncSessionLocal() as session:
                    post = await session.get(Post, post_id)
                    if post:
                        post.detected_language = "en"
                        await session.commit()
                return

            # Translate
            result = await translator.translate(
                text=content,
                target_lang="en",
                user_id=user_id,
            )

            async with AsyncSessionLocal() as session:
                post = await session.get(Post, post_id)
                if post:
                    post.detected_language = lang
                    if result.get("translated"):
                        post.translated_content = result["translated"]
                        post.translation_model = result.get("model_used", "unknown")
                        logger.debug(
                            "Auto-translated post %s from %s (%d chars)",
                            post_id, lang, len(result["translated"]),
                        )
                    await session.commit()

        except Exception as exc:
            logger.warning("Auto-translation failed for post %s: %s", post_id, exc)


def schedule_auto_translate(post_id: UUID, content: str, user_id: str) -> None:
    """Schedule auto-translation as a fire-and-forget async task.

    Call this from collectors after committing the post.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(auto_translate_post(post_id, content, user_id))
        else:
            loop.run_until_complete(auto_translate_post(post_id, content, user_id))
    except Exception as exc:
        logger.debug("Failed to schedule auto-translate for %s: %s", post_id, exc)
