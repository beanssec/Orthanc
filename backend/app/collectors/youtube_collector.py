"""YouTube transcript collector — fetches captions from configured channels."""
import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.models.source import Source

logger = logging.getLogger("orthanc.collectors.youtube")


class YouTubeCollector:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, sources: list):
        """Start polling YouTube channels."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(sources))
        logger.info("YouTubeCollector started with %d sources", len(sources))

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self, sources: list):
        while self._running:
            for source in sources:
                try:
                    await self._poll_channel(source)
                except Exception as e:
                    logger.error("YouTube poll error for %s: %s", source.display_name, e)
            await asyncio.sleep(1800)  # 30 minutes

    async def _poll_channel(self, source: Source):
        """Fetch recent videos from a YouTube channel/playlist."""
        handle = source.handle  # YouTube channel URL or @handle

        # Use yt-dlp to get video metadata (no download)
        # --playlist-end limits to last 5 videos to avoid bulk ingestion
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--flat-playlist",
            "--no-download",
            "--playlist-end", "5",  # Last 5 videos only
            f"https://www.youtube.com/{handle}/videos",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            logger.warning("yt-dlp timeout for %s", handle)
            return

        if proc.returncode != 0:
            logger.warning("yt-dlp error for %s: %s", handle, stderr.decode()[:200])
            return

        for line in stdout.decode().strip().split("\n"):
            if not line.strip():
                continue
            try:
                video = json.loads(line)
            except json.JSONDecodeError:
                continue

            video_id = video.get("id")
            if not video_id:
                continue

            external_id = f"youtube_{video_id}"

            # Check if already ingested
            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post).where(Post.external_id == external_id)
                )
                if existing.scalars().first():
                    continue

            # Fetch captions for this video
            transcript = await self._fetch_transcript(video_id)

            title = video.get("title", "")
            description = video.get("description", "")
            uploader = video.get("uploader", video.get("channel", ""))
            upload_date = video.get("upload_date", "")  # YYYYMMDD format
            duration = video.get("duration")
            view_count = video.get("view_count")

            # Parse upload date
            timestamp = datetime.now(timezone.utc)
            if upload_date and len(upload_date) == 8:
                try:
                    timestamp = datetime(
                        int(upload_date[:4]),
                        int(upload_date[4:6]),
                        int(upload_date[6:]),
                        tzinfo=timezone.utc,
                    )
                except ValueError:
                    pass

            # Build content: title + description + transcript
            content_parts = [f"📹 {title}"]
            if description:
                desc_short = description[:500] + ("..." if len(description) > 500 else "")
                content_parts.append(f"\n{desc_short}")
            if transcript:
                content_parts.append(f"\n\n--- TRANSCRIPT ---\n{transcript[:5000]}")
            if duration:
                mins = duration // 60
                content_parts.append(f"\n[Duration: {mins}min | Views: {view_count or 'N/A'}]")

            content = "\n".join(content_parts)

            # Store post
            async with AsyncSessionLocal() as session:
                post = Post(
                    source_type="youtube",
                    source_id=source.id,
                    external_id=external_id,
                    author=uploader,
                    content=content,
                    timestamp=timestamp,
                    ingested_at=datetime.now(timezone.utc),
                )
                session.add(post)

                # Update source last_polled
                src = await session.execute(select(Source).where(Source.id == source.id))
                src_obj = src.scalars().first()
                if src_obj:
                    src_obj.last_polled = datetime.now(timezone.utc)

                await session.commit()
                logger.info("Ingested YouTube: %s — %s", uploader, title[:60])

            # Run entity extraction (best-effort)
            try:
                from app.services.entity_extractor import extract_entities  # noqa: PLC0415
                await extract_entities(post.id, content)
            except Exception as e:
                logger.warning("Entity extraction failed for YouTube post: %s", e)

    async def _fetch_transcript(self, video_id: str) -> str:
        """Fetch auto-generated captions for a video."""
        cmd = [
            "yt-dlp",
            "--write-auto-subs",
            "--sub-lang", "en",
            "--skip-download",
            "--print", "%(subtitles)j",
            f"https://www.youtube.com/watch?v={video_id}",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except (asyncio.TimeoutError, Exception):
            return ""

        if proc.returncode != 0:
            return ""

        # Parse subtitle data — yt-dlp outputs subtitle info as JSON
        raw = stdout.decode().strip()
        if not raw or raw == "NA":
            return ""

        try:
            subs = json.loads(raw)
            # Get English auto-generated subs
            for lang_key in ["en", "en-orig"]:
                if lang_key in subs:
                    for fmt in subs[lang_key]:
                        if fmt.get("ext") == "vtt":
                            return await self._download_vtt(fmt["url"])
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return ""

    async def _download_vtt(self, url: str) -> str:
        """Download VTT subtitle file and extract plain text."""
        import httpx  # noqa: PLC0415

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=30)
                if resp.status_code != 200:
                    return ""
                vtt = resp.text
                lines = []
                for line in vtt.split("\n"):
                    line = line.strip()
                    if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
                        continue
                    if "-->" in line:  # timestamp line
                        continue
                    if line.startswith("<"):  # HTML tags
                        continue
                    # Remove duplicate lines (auto-subs repeat)
                    if not lines or line != lines[-1]:
                        lines.append(line)
                return " ".join(lines)
        except Exception:
            return ""


youtube_collector = YouTubeCollector()
