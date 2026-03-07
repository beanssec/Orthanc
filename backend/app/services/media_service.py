"""Media storage, thumbnailing, and metadata extraction service."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from typing import Optional

from PIL import Image

logger = logging.getLogger("orthanc.services.media")

MEDIA_DIR = "/app/data/media"
THUMBNAIL_DIR = "/app/data/media/thumbnails"
THUMBNAIL_WIDTH = 400


HASH_INDEX_PATH = os.path.join(MEDIA_DIR, ".hash_index.json")


class MediaService:
    """Handles media storage, thumbnailing, and metadata extraction."""

    def __init__(self) -> None:
        os.makedirs(MEDIA_DIR, exist_ok=True)
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        self._hash_index: dict[str, str] = {}  # sha256 -> relative_path
        self._load_hash_index()

    def _load_hash_index(self) -> None:
        """Load the content-hash → path index from disk."""
        if os.path.exists(HASH_INDEX_PATH):
            try:
                with open(HASH_INDEX_PATH, "r") as f:
                    self._hash_index = json.load(f)
                logger.info("Loaded media hash index: %d entries", len(self._hash_index))
            except Exception as exc:
                logger.warning("Failed to load hash index: %s", exc)
                self._hash_index = {}

    def _save_hash_index(self) -> None:
        """Persist the hash index to disk."""
        try:
            with open(HASH_INDEX_PATH, "w") as f:
                json.dump(self._hash_index, f)
        except Exception as exc:
            logger.warning("Failed to save hash index: %s", exc)

    def save_media(self, data: bytes, channel_id: str, message_id: int, extension: str) -> str:
        """Save media bytes to disk with content-hash dedup.
        
        If an identical file (by sha256) already exists, returns the
        existing path instead of writing a duplicate.
        Returns relative path (relative to MEDIA_DIR).
        """
        content_hash = hashlib.sha256(data).hexdigest()

        # Check if we already have this exact content
        existing = self._hash_index.get(content_hash)
        if existing and os.path.exists(os.path.join(MEDIA_DIR, existing)):
            logger.debug("Dedup hit: %s already stored at %s", content_hash[:12], existing)
            return existing

        # New content — write to disk
        subdir = str(channel_id)
        abs_subdir = os.path.join(MEDIA_DIR, subdir)
        os.makedirs(abs_subdir, exist_ok=True)
        filename = f"{message_id}.{extension}"
        relative_path = os.path.join(subdir, filename)
        abs_path = os.path.join(MEDIA_DIR, relative_path)
        with open(abs_path, "wb") as f:
            f.write(data)

        # Update index
        self._hash_index[content_hash] = relative_path
        self._save_hash_index()

        logger.debug("Saved media: %s (%d bytes, hash %s)", relative_path, len(data), content_hash[:12])
        return relative_path

    def abs_path(self, relative_path: str) -> str:
        """Convert a stored relative media path to its absolute path."""
        return os.path.join(MEDIA_DIR, relative_path)

    def abs_thumb_path(self, relative_thumb_path: str) -> str:
        """Convert a stored relative thumbnail path to its absolute path."""
        return os.path.join(THUMBNAIL_DIR, relative_thumb_path)

    def generate_thumbnail(self, relative_media_path: str, message_id: int) -> Optional[str]:
        """
        Generate a thumbnail for an image.
        Returns relative thumbnail path (relative to THUMBNAIL_DIR) or None on failure.
        """
        abs_src = os.path.join(MEDIA_DIR, relative_media_path)
        try:
            img = Image.open(abs_src)
            if img.width == 0:
                return None
            ratio = THUMBNAIL_WIDTH / img.width
            new_height = max(1, int(img.height * ratio))
            img = img.resize((THUMBNAIL_WIDTH, new_height), Image.LANCZOS)
            # Convert to RGB if needed (handles RGBA, palette, etc.)
            if img.mode in ("RGBA", "P", "LA", "CMYK"):
                img = img.convert("RGB")
            thumb_filename = f"{message_id}_thumb.jpg"
            thumb_abs = os.path.join(THUMBNAIL_DIR, thumb_filename)
            img.save(thumb_abs, "JPEG", quality=80, optimize=True)
            logger.debug("Generated thumbnail: %s", thumb_filename)
            return thumb_filename  # relative to THUMBNAIL_DIR
        except Exception as exc:
            logger.warning("Thumbnail generation failed for %s: %s", relative_media_path, exc)
            return None

    def extract_image_metadata(self, relative_path: str) -> dict:
        """Extract EXIF and file metadata from an image. Returns dict (never raises)."""
        abs_path = os.path.join(MEDIA_DIR, relative_path)
        metadata: dict = {}
        try:
            # File hash
            with open(abs_path, "rb") as f:
                file_bytes = f.read()
            metadata["sha256"] = hashlib.sha256(file_bytes).hexdigest()
            metadata["file_size"] = len(file_bytes)

            img = Image.open(abs_path)
            metadata["width"] = img.width
            metadata["height"] = img.height
            metadata["format"] = img.format

            # EXIF data
            exif = img.getexif()
            if exif:
                # Key EXIF tags we care about
                IMPORTANT_TAGS: dict[int, str] = {
                    271: "camera_make",
                    272: "camera_model",
                    274: "orientation",
                    305: "software",      # Reveals Photoshop, DALL-E, Midjourney, etc.
                    306: "datetime",
                    36867: "datetime_original",
                    36868: "datetime_digitized",
                    34853: "gps_info",
                    37510: "user_comment",
                    40962: "pixel_x_dimension",
                    40963: "pixel_y_dimension",
                }
                exif_dict: dict = {}
                for tag_id, tag_name in IMPORTANT_TAGS.items():
                    if tag_id in exif:
                        val = exif[tag_id]
                        if isinstance(val, bytes):
                            try:
                                val = val.decode("utf-8", errors="replace")
                            except Exception:
                                val = val.hex()
                        exif_dict[tag_name] = str(val)

                if exif_dict:
                    metadata["exif"] = exif_dict
                    # Flag known AI-generation software in EXIF
                    software = exif_dict.get("software", "").lower()
                    ai_indicators = [
                        "dall-e", "midjourney", "stable diffusion",
                        "comfyui", "automatic1111", "novelai", "adobe firefly",
                        "imagen", "bing image creator",
                    ]
                    if any(ind in software for ind in ai_indicators):
                        metadata["ai_software_detected"] = True
                        metadata["ai_software_name"] = exif_dict.get("software")
                else:
                    metadata["exif"] = None
                    metadata["exif_stripped"] = True
            else:
                metadata["exif"] = None
                metadata["exif_stripped"] = True

        except Exception as exc:
            logger.warning("Image metadata extraction failed for %s: %s", relative_path, exc)
            metadata["error"] = str(exc)

        return metadata

    def extract_video_metadata(self, relative_path: str) -> dict:
        """Extract video metadata using ffprobe. Gracefully handles missing ffprobe."""
        abs_path = os.path.join(MEDIA_DIR, relative_path)
        metadata: dict = {}
        try:
            with open(abs_path, "rb") as f:
                metadata["sha256"] = hashlib.sha256(f.read()).hexdigest()
            metadata["file_size"] = os.path.getsize(abs_path)

            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", abs_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                probe = json.loads(result.stdout)
                fmt = probe.get("format", {})
                duration = fmt.get("duration")
                metadata["duration_seconds"] = float(duration) if duration else None
                metadata["format_name"] = fmt.get("format_name")
                metadata["bit_rate"] = fmt.get("bit_rate")

                for stream in probe.get("streams", []):
                    if stream.get("codec_type") == "video":
                        metadata["video_codec"] = stream.get("codec_name")
                        metadata["width"] = stream.get("width")
                        metadata["height"] = stream.get("height")
                        metadata["fps"] = stream.get("r_frame_rate")
                    elif stream.get("codec_type") == "audio":
                        metadata["audio_codec"] = stream.get("codec_name")
            else:
                metadata["ffprobe_error"] = result.stderr[:200] if result.stderr else "unknown"

        except FileNotFoundError:
            metadata["ffprobe_available"] = False
        except subprocess.TimeoutExpired:
            metadata["error"] = "ffprobe timed out"
        except Exception as exc:
            logger.warning("Video metadata extraction failed for %s: %s", relative_path, exc)
            metadata["error"] = str(exc)

        return metadata


media_service = MediaService()
