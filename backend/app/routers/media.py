"""Media serving endpoints — serves downloaded images/videos for posts."""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
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
