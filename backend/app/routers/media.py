"""Media serving endpoints — serves downloaded images/videos for posts."""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db, AsyncSessionLocal
from app.models import User, Post
from app.middleware.auth import get_current_user
from app.services.media_service import MEDIA_DIR, THUMBNAIL_DIR

logger = logging.getLogger("orthanc.routers.media")

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{post_id}")
async def get_post_media(
    post_id: uuid.UUID,
    thumb: bool = Query(default=False, description="Serve thumbnail instead of full media"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """
    Serve media file for a post.
    - ?thumb=true  → serves the thumbnail (JPEG, max 400px wide)
    - ?thumb=false → serves the full media file
    Auth-gated: requires a valid Bearer token.
    """
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not post.media_path:
        raise HTTPException(status_code=404, detail="This post has no downloaded media")

    if thumb:
        if not post.media_thumbnail_path:
            raise HTTPException(status_code=404, detail="No thumbnail available for this post")
        abs_path = os.path.join(THUMBNAIL_DIR, post.media_thumbnail_path)
        media_type = "image/jpeg"
    else:
        abs_path = os.path.join(MEDIA_DIR, post.media_path)
        media_type = post.media_mime or "application/octet-stream"

    if not os.path.isfile(abs_path):
        logger.warning("Media file not found on disk: %s (post %s)", abs_path, post_id)
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    return FileResponse(
        path=abs_path,
        media_type=media_type,
        filename=os.path.basename(abs_path),
    )


@router.post("/reanalyze")
async def reanalyze_media(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run authenticity analysis on images that haven't been checked or failed."""
    from app.services.authenticity_analyzer import authenticity_analyzer
    from app.services.collector_manager import collector_manager
    from app.services.media_service import MEDIA_DIR
    import asyncio, json

    # Get AI keys — prefer OpenRouter (GPT-4o vision), fall back to xAI
    user_id = str(current_user.id)
    keys = await collector_manager.get_keys(user_id, "openrouter")
    provider = "openrouter"
    api_key = keys.get("api_key") if keys else None
    if not api_key:
        keys = await collector_manager.get_keys(user_id, "x")
        if keys:
            api_key = keys.get("api_key")
            provider = "xai"
    if not api_key:
        return {"error": "No AI credentials configured (xAI or OpenRouter required for image analysis)"}

    # Find unchecked images
    result = await db.execute(
        select(Post).where(
            Post.media_type == "image",
            Post.authenticity_score.is_(None),
        ).limit(20)
    )
    posts = result.scalars().all()

    queued = 0
    for post in posts:
        filepath = f"{MEDIA_DIR}/{post.media_path}"
        import os
        if not os.path.exists(filepath):
            continue

        async def _analyze(p=post, fp=filepath):
            try:
                res = await authenticity_analyzer.analyze_image(fp, p.media_metadata or {}, api_key, provider)
                async with AsyncSessionLocal() as sess:
                    db_post = await sess.get(Post, p.id)
                    if db_post and res:
                        db_post.authenticity_score = res.get("score")
                        db_post.authenticity_analysis = json.dumps(res)
                    if db_post:
                        from datetime import datetime, timezone
                        db_post.authenticity_checked_at = datetime.now(timezone.utc)
                    await sess.commit()
            except Exception:
                pass

        asyncio.ensure_future(_analyze())
        queued += 1

    return {"queued": queued, "provider": provider, "message": f"Queued {queued} images for analysis"}
