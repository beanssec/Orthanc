"""AI intelligence brief generator — multi-model support."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.models.brief import Brief
from app.services.ai_models import get_model, AI_MODELS
from app.services.model_router import model_router
from sqlalchemy import select

logger = logging.getLogger("orthanc.brief_generator")

SYSTEM_PROMPT = (
    "You are an OSINT intelligence analyst. Generate a structured intelligence brief from the "
    "following recent posts. Include:\n"
    "1) Executive Summary (2-3 sentences)\n"
    "2) Key Developments (bullet points)\n"
    "3) Potential Threats/Concerns\n"
    "4) Entities of Interest (people, organizations, locations that appear significant)\n\n"
    "Be concise, analytical, and professional. Avoid speculation beyond the available data."
)

DEFAULT_MODEL = "grok-3-mini"


class BriefGenerator:
    """Generates AI intelligence summaries from recent posts."""

    async def generate_brief(
        self,
        user_id: str,
        hours: int = 24,
        model_id: str | None = None,
        topic: str | None = None,
        source_types: list[str] | None = None,
        custom_prompt: str | None = None,
    ) -> dict:
        """Generate an intelligence brief using the specified model.
        
        Args:
            topic: Optional keyword/topic filter — only posts containing this text
            source_types: Optional list of source types to include (e.g. ["rss", "telegram"])
            custom_prompt: Optional custom system prompt override
        """

        model_id = model_id or DEFAULT_MODEL
        model_config = get_model(model_id)
        if not model_config:
            return {"error": f"Unknown model: {model_id}. Available: {[m['id'] for m in AI_MODELS]}"}

        # Fetch recent posts with optional filters
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with AsyncSessionLocal() as session:
            query = select(Post).where(Post.timestamp >= cutoff)

            # Source type filter
            if source_types:
                query = query.where(Post.source_type.in_(source_types))

            # Topic/keyword filter (ILIKE for MVP)
            if topic and topic.strip():
                keyword = f"%{topic.strip()}%"
                query = query.where(Post.content.ilike(keyword))

            query = query.order_by(Post.timestamp.desc()).limit(200)
            result = await session.execute(query)
            posts = result.scalars().all()

        if not posts:
            return {
                "summary": "No posts found in the selected time period.",
                "post_count": 0,
                "time_range_hours": hours,
                "model": model_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Use more posts for large-context models
        context_window = model_config.get("context_window", 128000)
        max_posts = 100 if context_window >= 500000 else 50
        max_chars = 500 if context_window >= 500000 else 300

        post_texts = []
        for p in posts[:max_posts]:
            ts_str = p.timestamp.strftime("%Y-%m-%d %H:%M UTC") if p.timestamp else "unknown time"
            text = (p.content or "")[:max_chars]
            post_texts.append(f"[{p.source_type.upper()}] [{ts_str}] {p.author}: {text}")

        context = "\n---\n".join(post_texts)

        # Build the system prompt — use custom if provided, otherwise default
        system_prompt = custom_prompt if custom_prompt and custom_prompt.strip() else SYSTEM_PROMPT

        # Build the user message with filter context
        filter_desc_parts = []
        if topic:
            filter_desc_parts.append(f'filtered by topic "{topic}"')
        if source_types:
            filter_desc_parts.append(f"from sources: {', '.join(source_types)}")
        filter_desc = f" ({', '.join(filter_desc_parts)})" if filter_desc_parts else ""

        user_message = (
            f"Generate an intelligence brief from these {len(posts)} recent "
            f"posts (last {hours} hours{filter_desc}):\n\n{context}"
        )

        logger.info(
            "Generating brief: user=%s model=%s posts=%d hours=%d topic=%s sources=%s",
            user_id, model_id, len(posts), hours, topic, source_types,
        )

        # If no model providers are registered for this session, fail fast with
        # a clear user-facing message instead of raising noisy internal errors.
        if not model_router._providers:
            return {
                "error": "No AI provider configured for this session. Add credentials in Settings -> Credentials and log in again.",
                "post_count": len(posts),
                "time_range_hours": hours,
                "model": model_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            result = await model_router.chat(
                task="brief",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                model=model_id,
                temperature=0.3,
            )
            brief_text = result["content"]
        except Exception as e:
            logger.error("Failed to generate brief (%s): %s", model_id, e)
            return {"error": f"Brief generation failed: {str(e)}"}

        generated_at = datetime.now(timezone.utc)
        cost_estimate = model_config["cost_estimate_per_brief"]

        # Persist the brief to the database
        brief_record = Brief(
            user_id=uuid.UUID(user_id),
            model=model_id,
            model_name=model_config["name"],
            hours=hours,
            post_count=len(posts),
            summary=brief_text,
            cost_estimate=cost_estimate,
            generated_at=generated_at,
        )
        async with AsyncSessionLocal() as session:
            session.add(brief_record)
            await session.commit()
            await session.refresh(brief_record)
            brief_id = str(brief_record.id)

        return {
            "id": brief_id,
            "summary": brief_text,
            "post_count": len(posts),
            "time_range_hours": hours,
            "model": model_id,
            "model_name": model_config["name"],
            "cost_estimate": cost_estimate,
            "generated_at": generated_at.isoformat(),
        }


brief_generator = BriefGenerator()
