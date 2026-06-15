"""
Anime Intelligence Brief Generator
====================================
Generates a short 90s cyberpunk anime-style video from the latest intelligence brief.

Pipeline:
  1. fetch_latest_brief()        — pull most recent brief from DB, extract executive_summary
  2. split_into_sentences()      — split executive summary into individual sentences
  3. generate_scene_prompts()    — LLM converts sentences → cyberpunk anime scene descriptions
  4. generate_video_clip_gemini()— Veo 3 generates each video clip WITH native audio
  5. generate_voiceover()        — Gemini native audio generates narration for each sentence
  6. _composite_clip()           — ffmpeg mixes video + ambient audio + voiceover + text overlay
  7. stitch_clips()              — ffmpeg concat with intro/outro cards
  8. generate_anime_brief()      — top-level orchestrator

Dependencies:
  pip install google-genai httpx

ffmpeg:
  Required for video stitching. Add to Dockerfile:
    RUN apt-get update && apt-get install -y ffmpeg
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_BASE = os.getenv("ORTHANC_ANIME_BRIEF_OUTPUT_DIR", "/app/data/output/anime_briefs")

CYBERPUNK_SCENE_SYSTEM_PROMPT = """You are a visual director creating scene descriptions for a 1990s cyberpunk anime intelligence briefing video.

For each sentence from an intelligence summary, create a vivid scene description suitable for AI video generation.

VISUAL STYLE (apply to ALL scenes):
- 1990s cyberpunk anime aesthetic — Ghost in the Shell, Akira, Psycho-Pass, Texhnolyze
- Dark, gritty atmosphere with film grain and chromatic aberration
- Neon lighting: cyan, magenta, amber against deep shadows
- CRT monitors, holographic displays, brutalist architecture
- Rain-slicked surfaces, steam vents, industrial decay
- Characters: anime-style military/intelligence operatives in tactical gear or long coats

SCENE DIRECTION RULES:
- Each scene MUST reflect the SPECIFIC content of its sentence (locations, actors, events)
- Include camera direction (tracking shot, close-up, slow dolly, aerial view, etc.)
- Include specific motion and action — no static scenes
- Include AUDIO CUES at the end (ambient sounds, effects that match the scene)
- Keep each description 3-5 sentences plus audio line
- Make each scene visually DISTINCT from the others

OUTPUT FORMAT: JSON array of objects with keys:
- "scene_number": int
- "narration_text": the original sentence (verbatim, for voiceover)
- "video_prompt": the full visual scene description including audio cues
- "overlay_text": short 1-line label for the scene (max 50 chars)

Output ONLY the JSON array. No markdown, no explanation."""

# OpenRouter experimental video models — tried in order (fallback only)
OPENROUTER_VIDEO_MODELS = [
    "alibaba/wan-2.6",
    "bytedance/seedance-1.5-pro",
    "google/veo-3.1",
    "openai/sora-2-pro",
]

# ---------------------------------------------------------------------------
# Step 1: Fetch latest brief from DB
# ---------------------------------------------------------------------------


async def fetch_latest_brief(brief_id: str | None = None) -> dict | None:
    """Fetch the most recent intelligence brief and extract the executive summary."""
    try:
        from app.db import AsyncSessionLocal  # type: ignore[import]
        from sqlalchemy import text  # type: ignore[import]
    except ImportError as exc:
        logger.error("Cannot import DB dependencies: %s", exc)
        return None

    try:
        async with AsyncSessionLocal() as session:
            if brief_id:
                result = await session.execute(
                    text("SELECT id, summary, generated_at, hours, post_count FROM briefs WHERE id = :id LIMIT 1"),
                    {"id": brief_id},
                )
            else:
                result = await session.execute(
                    text("SELECT id, summary, generated_at, hours, post_count FROM briefs ORDER BY generated_at DESC LIMIT 1")
                )
            row = result.first()
    except Exception as exc:
        logger.error("Database query failed: %s", exc)
        return None

    if not row:
        return None

    # The summary column contains JSON (sometimes wrapped in ```json ... ```)
    raw = row.summary
    # Strip markdown code fences
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse brief JSON")
        return None

    return {
        "id": str(row.id),
        "executive_summary": data.get("executive_summary", ""),
        "generated_at": str(row.generated_at),
        "hours": row.hours,
        "post_count": row.post_count,
        "key_developments": data.get("key_developments", []),
    }


# ---------------------------------------------------------------------------
# Step 2: Split executive summary into sentences
# ---------------------------------------------------------------------------


def split_into_sentences(text: str) -> list[str]:
    """Split executive summary into individual sentences."""
    # Split on sentence-ending punctuation followed by space or end
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter out very short fragments
    return [s.strip() for s in sentences if len(s.strip()) > 20]


# ---------------------------------------------------------------------------
# Step 3: Scene prompt generation via OpenRouter LLM
# ---------------------------------------------------------------------------


def _extract_json_array(text: str) -> list[dict]:
    """Try to extract a JSON array from LLM output that might have extra text."""
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Look for [...] block
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    logger.error("Could not extract JSON array from LLM response:\n%s", text[:500])
    return []


async def generate_scene_prompts(sentences: list[str], api_key: str) -> list[dict]:
    """
    Use OpenRouter LLM to convert executive summary sentences into cyberpunk scene prompt dicts.

    Returns a list of dicts with keys:
      scene_number, narration_text, video_prompt, overlay_text
    """
    if not sentences:
        return []

    if not api_key:
        logger.error("No OpenRouter API key provided — cannot generate scene prompts")
        return _fallback_scene_prompts(sentences)

    user_prompt = "Here are the sentences from an intelligence executive summary. Create one cyberpunk anime scene per sentence:\n\n"
    for i, s in enumerate(sentences, 1):
        user_prompt += f"Sentence {i}: {s}\n"
    user_prompt += f"\nGenerate exactly {len(sentences)} scene objects."

    # Try grok-3-mini first, fall back to gpt-4o-mini
    models_to_try = ["x-ai/grok-3-mini", "openai/gpt-4o-mini"]
    last_error: Exception | None = None

    for model in models_to_try:
        try:
            logger.info("Generating scene prompts with model: %s", model)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://orthanc.osint",
                        "X-Title": "Orthanc Anime Brief",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": CYBERPUNK_SCENE_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.8,
                        "max_tokens": 2000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            logger.debug("LLM scene prompt response:\n%s", content[:1000])

            scenes = _extract_json_array(content)
            if scenes:
                logger.info("Generated %d scene prompts", len(scenes))
                return scenes

            logger.warning("Empty scene list from model %s, trying next", model)

        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP error from %s: %s", model, exc)
            last_error = exc
        except Exception as exc:
            logger.warning("Error with model %s: %s", model, exc)
            last_error = exc

    logger.error("All LLM models failed (%s) — using fallback prompts", last_error)
    return _fallback_scene_prompts(sentences)


def _fallback_scene_prompts(sentences: list[str]) -> list[dict]:
    """Generate cyberpunk scene prompts without LLM."""
    scenes = []

    # Rotating camera directions and settings for variety
    camera_styles = [
        "Slow tracking shot through",
        "Close-up inside",
        "Aerial dolly shot over",
        "Low-angle shot looking up at",
        "Handheld shaky-cam moving through",
        "Slow zoom into",
    ]

    settings = [
        "a rain-soaked neon-lit command bunker, CRT monitors flickering with intelligence feeds, cyan and magenta light cutting through cigarette smoke",
        "a dark underground war room, massive holographic globe rotating with red alert markers, operators in tactical gear hunched over terminals",
        "a brutalist government tower at night, rain streaming down floor-to-ceiling windows, a lone figure studying classified documents by the glow of multiple screens",
        "a cyberpunk street-level intelligence post, neon signs reflecting in rain puddles, encrypted data scrolling across shop-front displays",
        "a militarized control centre deep underground, banks of radar screens and satellite feeds, red emergency lighting casting harsh shadows",
        "a dim diplomatic chamber with holographic table projecting conflict zones, figures in dark coats facing each other across the blue glow",
    ]

    audio_cues = [
        "Sound: low analog synth drone, distant thunder, static-laced radio chatter, keyboard clicks",
        "Sound: urgent alarm klaxon fading in, muffled explosions, electronic beeping, ventilation hum",
        "Sound: rain hitting glass, distant sirens, paper shuffling, encrypted comms bursts",
        "Sound: street-level rain and traffic, neon buzz, fragmented news broadcasts in multiple languages",
        "Sound: deep mechanical hum, sonar pings, boots on metal grating, hushed tactical radio",
        "Sound: echoing footsteps, diplomatic murmuring, holographic interface sounds, clock ticking",
    ]

    for i, sentence in enumerate(sentences):
        idx = i % len(camera_styles)

        prompt = (
            f"1990s cyberpunk anime, dark gritty atmosphere, film grain, chromatic aberration. "
            f"{camera_styles[idx]} {settings[idx]}. "
            f"The scene evokes: {sentence[:150]}. "
            f"{audio_cues[idx]}"
        )

        # Generate short overlay from sentence
        overlay = sentence[:47] + "..." if len(sentence) > 50 else sentence

        scenes.append({
            "scene_number": i + 1,
            "narration_text": sentence,
            "video_prompt": prompt,
            "overlay_text": overlay,
        })

    return scenes


# ---------------------------------------------------------------------------
# Step 4: Video generation — Gemini Veo 3 (primary)
# ---------------------------------------------------------------------------


async def generate_video_clip_gemini(
    prompt: str, output_path: str, api_key: str
) -> bool:
    """
    Generate a video clip using Google's Veo 3 model via the Gemini API.
    The prompt should include audio cues — Veo 3 will generate matching ambient audio natively.

    Requires: pip install google-genai
    """
    try:
        from google import genai  # type: ignore[import]
        from google.genai import types as genai_types  # type: ignore[import]
    except ImportError:
        logger.error(
            "google-genai package not installed. "
            "Run: pip install google-genai\n"
            "Also add to requirements.txt / Dockerfile."
        )
        return False

    logger.info("Generating Gemini Veo 3 clip: %s...", prompt[:80])

    def _generate_sync() -> bytes | None:
        """Submit video generation and poll until complete. Returns raw video bytes or None."""
        client = genai.Client(api_key=api_key)

        # Try models in order of preference (fast first for speed)
        veo_models = [
            "veo-3.0-fast-generate-001",
            "veo-3.0-generate-001",
            "veo-3.1-fast-generate-preview",
            "veo-2.0-generate-001",
        ]
        operation = None
        for veo_model in veo_models:
            try:
                logger.info("Trying Veo model: %s", veo_model)
                operation = client.models.generate_videos(
                    model=veo_model,
                    prompt=prompt,
                    config=genai_types.GenerateVideosConfig(
                        aspect_ratio="16:9",
                        number_of_videos=1,
                    ),
                )
                logger.info("Veo %s accepted (op: %s)", veo_model, getattr(operation, 'name', '?'))
                break
            except Exception as model_exc:
                logger.debug("Veo model %s failed: %s", veo_model, model_exc)
                continue

        if operation is None:
            logger.error("All Veo models failed to accept the request")
            return None

        # Poll using client.operations.get(operation) — the operation.done
        # property does NOT auto-refresh; we must re-fetch from the server.
        max_polls = 120  # 20 min max
        for poll_num in range(max_polls):
            try:
                refreshed = client.operations.get(operation)
                if refreshed.done:
                    logger.info("Veo completed after %d polls (~%ds)", poll_num, poll_num * 10)
                    # Download video bytes via the Files API
                    vid = refreshed.result.generated_videos[0].video
                    file_id = vid.uri.split("/files/")[1].split(":")[0]
                    logger.info("Downloading video file: %s", file_id)
                    video_bytes = client.files.download(file=file_id)
                    return video_bytes
            except Exception as exc:
                logger.warning("Poll %d error: %s", poll_num, exc)

            if poll_num % 3 == 0:
                logger.debug("Veo poll %d/%d — still generating...", poll_num + 1, max_polls)
            time.sleep(10)

        logger.error("Veo generation timed out after 20 minutes")
        return None

    try:
        video_data = await asyncio.get_event_loop().run_in_executor(None, _generate_sync)
    except Exception as exc:
        logger.error("Veo 3 generation failed: %s", exc)
        return False

    if not video_data or not isinstance(video_data, bytes):
        logger.error("Veo 3 did not return video bytes")
        return False

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(video_data)
        logger.info("Saved Veo 3 clip (%d bytes, %.1f MB) → %s",
                     len(video_data), len(video_data) / 1024 / 1024, output_path)
        return True
    except Exception as exc:
        logger.error("Failed to save Veo 3 clip: %s", exc, exc_info=True)
        return False


async def _download_uri(uri: str, api_key: str) -> bytes | None:
    """Download video from a Google API URI, attaching the API key."""
    try:
        url = uri
        if "googleapis.com" in uri and "key=" not in uri:
            sep = "&" if "?" in uri else "?"
            url = f"{uri}{sep}key={api_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as exc:
        logger.error("Failed to download video URI %s: %s", uri, exc)
        return None


# ---------------------------------------------------------------------------
# Step 4b: Video generation — OpenRouter (fallback)
# ---------------------------------------------------------------------------


async def generate_video_clip_openrouter(
    prompt: str, output_path: str, api_key: str
) -> bool:
    """
    Try OpenRouter's experimental video generation models.
    Fallback when Gemini is unavailable.
    """
    for model in OPENROUTER_VIDEO_MODELS:
        logger.info("Attempting OpenRouter video gen with model: %s", model)
        data: dict = {}

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://orthanc.osint",
                        "X-Title": "Orthanc Anime Brief",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "OpenRouter %s HTTP %s — trying next model",
                model, exc.response.status_code,
            )
            continue
        except Exception as exc:
            logger.warning("OpenRouter %s request failed: %s — trying next", model, exc)
            continue

        logger.info("OpenRouter %s responded — parsing video output...", model)
        logger.debug("Raw response: %s", json.dumps(data)[:1000])

        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )

        if not content:
            logger.warning("OpenRouter %s returned empty content — trying next", model)
            continue

        logger.debug("%s content: %s", model, content[:500])

        # Attempt 1: content contains a video URL
        url_match = re.search(r"https?://\S+\.(mp4|webm|mov)\b", content, re.IGNORECASE)
        if not url_match:
            url_match = re.search(r"https?://\S+", content)

        if url_match:
            video_url = url_match.group().rstrip(".,;\"')")
            logger.info("%s returned a URL: %s", model, video_url)
            video_data = await _download_uri(video_url, "")
            if video_data and len(video_data) > 10000:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(video_data)
                logger.info("Saved %s clip (%d bytes) → %s", model, len(video_data), output_path)
                return True

        # Attempt 2: content is base64-encoded video
        b64_content = content
        if "base64," in b64_content:
            b64_content = b64_content.split("base64,", 1)[1].strip()

        if len(b64_content) > 1000 and re.match(r"^[A-Za-z0-9+/=\s]+$", b64_content[:200]):
            try:
                video_data = base64.b64decode(b64_content.strip())
                if len(video_data) > 10000:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(video_data)
                    logger.info(
                        "Decoded base64 %s clip (%d bytes) → %s",
                        model, len(video_data), output_path
                    )
                    return True
            except Exception as exc:
                logger.debug("base64 decode attempt failed: %s", exc)

        # Attempt 3: JSON with video URL/data field
        try:
            payload = json.loads(content)
            for key in ("url", "video_url", "video", "uri", "download_url", "file_url"):
                if vid_url := payload.get(key):
                    video_data = await _download_uri(vid_url, "")
                    if video_data and len(video_data) > 10000:
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        Path(output_path).write_bytes(video_data)
                        logger.info("Saved %s clip from JSON field → %s", model, output_path)
                        return True
        except (json.JSONDecodeError, AttributeError):
            pass

        logger.warning(
            "OpenRouter %s — could not extract video. Content snippet: %s",
            model, content[:200],
        )

    logger.error("All OpenRouter video models failed for this clip")
    return False


# ---------------------------------------------------------------------------
# Step 5: Voiceover generation with Gemini native audio
# ---------------------------------------------------------------------------


async def generate_voiceover(sentence: str, output_path: str, api_key: str) -> bool:
    """Generate voiceover narration using Gemini native audio model."""
    try:
        from google import genai  # type: ignore[import]
    except ImportError:
        logger.error("google-genai package not installed — cannot generate voiceover")
        return False

    client = genai.Client(api_key=api_key)

    speech_prompt = (
        "Read the following intelligence briefing text aloud. "
        "Use a calm, low, measured tone. Male voice, deep register. "
        "Deliver as a classified intelligence briefing — detached, professional, unhurried. "
        "Slight pause between clauses. No emotion, no inflection on dramatic content. "
        "The gravity comes from the words, not the delivery.\n\n"
        f"Text: {sentence}"
    )

    def _save_pcm_to_wav(pcm_data: bytes, filepath: str, channels: int = 1, rate: int = 24000, sample_width: int = 2) -> None:
        """Save raw PCM16 audio data to a WAV file."""
        import wave
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(pcm_data)

    def _generate_voiceover_sync() -> bytes | None:
        """Try multiple approaches to generate TTS audio."""
        from google.genai import types as genai_types  # type: ignore[import]

        # TTS models to try in order
        tts_models = [
            "gemini-2.5-flash-preview-tts",
            "gemini-2.5-pro-preview-tts",
            "gemini-2.5-flash-native-audio-latest",
        ]
        # Voices to try — deep male for the cyberpunk briefing feel
        voices = ["Orus", "Charon", "Fenrir"]

        for model in tts_models:
            for voice in voices:
                try:
                    logger.info("Trying voiceover: model=%s voice=%s", model, voice)
                    response = client.models.generate_content(
                        model=model,
                        contents=speech_prompt,
                        config=genai_types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=genai_types.SpeechConfig(
                                voice_config=genai_types.VoiceConfig(
                                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                        voice_name=voice,
                                    )
                                )
                            ),
                        ),
                    )
                    # Extract PCM audio from response
                    if response and response.candidates:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                                audio_data = part.inline_data.data
                                mime = getattr(part.inline_data, "mime_type", "unknown")
                                logger.info(
                                    "Voiceover success: model=%s voice=%s mime=%s bytes=%d",
                                    model, voice, mime, len(audio_data),
                                )
                                return audio_data
                    logger.debug("No audio parts in response for model=%s voice=%s", model, voice)
                except Exception as exc:
                    logger.debug("Voiceover failed: model=%s voice=%s error=%s", model, voice, exc)
                    continue

        logger.warning("All voiceover models/voices exhausted — no audio generated")
        return None

    try:
        audio_data = await asyncio.get_event_loop().run_in_executor(None, _generate_voiceover_sync)
    except Exception as exc:
        logger.error("Voiceover generation failed: %s", exc)
        return False

    if not audio_data:
        logger.warning("No audio data returned for voiceover")
        return False

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        # Gemini TTS outputs raw PCM16 at 24kHz — save as WAV
        _save_pcm_to_wav(audio_data, output_path)
        logger.info("Saved voiceover WAV (%d bytes PCM) → %s", len(audio_data), output_path)
        return True
    except Exception as exc:
        logger.error("Failed to save voiceover: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Step 6: ffmpeg compositing
# ---------------------------------------------------------------------------


def _check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def _ffmpeg_escape(text: str) -> str:
    """Escape text for ffmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    return text


def _add_text_overlay(input_path: str, output_path: str, overlay_text: str) -> bool:
    """Add a text overlay to a video clip using ffmpeg drawtext."""
    escaped = _ffmpeg_escape(overlay_text)

    drawtext_filter = (
        f"drawtext="
        f"text='{escaped}':"
        f"fontsize=24:"
        f"fontcolor=white:"
        f"x=(w-text_w)/2:"
        f"y=h-th-30:"
        f"box=1:"
        f"boxcolor=black@0.6:"
        f"boxborderw=8"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", drawtext_filter,
        "-c:a", "copy",
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error("ffmpeg drawtext failed:\n%s", result.stderr[-1000:])
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg drawtext timed out for %s", input_path)
        return False
    except Exception as exc:
        logger.error("ffmpeg drawtext error: %s", exc)
        return False


def _composite_clip(video_path: str, voiceover_path: str, output_path: str, overlay_text: str) -> bool:
    """Composite video + voiceover + text overlay into a single clip.

    Mixes voiceover narration on top of the video's ambient audio:
    - Ambient (Veo 3 native audio): 30% volume
    - Voiceover narration: 100% volume
    """
    if not os.path.exists(voiceover_path):
        # No voiceover — just add text overlay to video
        return _add_text_overlay(video_path, output_path, overlay_text)

    escaped = _ffmpeg_escape(overlay_text)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,        # input 0: video with ambient audio
        "-i", voiceover_path,    # input 1: voiceover
        "-filter_complex",
        f"[0:a]volume=0.3[ambient];"                                 # reduce ambient to 30%
        f"[ambient][1:a]amix=inputs=2:duration=shortest[aout];"      # mix audio
        f"[0:v]drawtext=text='{escaped}':"
        f"fontsize=24:fontcolor=white:"
        f"x=(w-text_w)/2:y=h-th-30:"
        f"box=1:boxcolor=black@0.6:boxborderw=8[vout]",
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error("ffmpeg composite failed: %s", result.stderr[-500:])
            # Fallback: just text overlay without audio mixing
            return _add_text_overlay(video_path, output_path, overlay_text)
        return True
    except Exception as exc:
        logger.error("ffmpeg composite error: %s", exc)
        return False


def _make_title_card(output_path: str, text: str, duration: int = 3, color: str = "black") -> bool:
    """Generate a static title card using ffmpeg lavfi."""
    lines = text.split("\n")

    if len(lines) == 1:
        vf = (
            f"color=c={color}:s=1920x1080:d={duration},"
            f"drawtext=text='{_ffmpeg_escape(lines[0])}':"
            f"fontsize=48:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"box=1:boxcolor=black@0.4:boxborderw=12"
        )
    else:
        dt_filters = []
        for i, line in enumerate(lines):
            y_expr = f"(h-text_h)/2+{(i - len(lines)//2) * 60}"
            dt_filters.append(
                f"drawtext=text='{_ffmpeg_escape(line)}':"
                f"fontsize=48:fontcolor=white:"
                f"x=(w-text_w)/2:y={y_expr}:"
                f"box=1:boxcolor=black@0.4:boxborderw=12"
            )
        vf = f"color=c={color}:s=1920x1080:d={duration}," + ",".join(dt_filters)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", vf,
        "-t", str(duration),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning("ffmpeg title card failed:\n%s", result.stderr[-500:])
            return False
        return True
    except Exception as exc:
        logger.warning("ffmpeg title card error: %s", exc)
        return False


async def stitch_clips(
    clips: list[dict],  # [{"path": str, "overlay_text": str, "narrative_title": str}]
    output_path: str,
    title: str = "INTELLIGENCE BRIEF // CLASSIFIED",
) -> str:
    """
    Stitch video clips together using ffmpeg concat.
    Clips already have composited audio (ambient + voiceover) and overlays applied.

    Returns output_path (even if only clips are present on ffmpeg absence).
    """
    if not _check_ffmpeg():
        logger.warning(
            "ffmpeg not found — cannot stitch clips. "
            "Install ffmpeg (apt-get install ffmpeg) or add to Dockerfile. "
            "Individual clips are available in: %s",
            str(Path(output_path).parent),
        )
        return str(Path(output_path).parent)

    work_dir = Path(output_path).parent
    processed_clips: list[str] = []

    # --- Intro card — styled like a terminal/CRT boot sequence ---
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    intro_text = f"{title}\n{now_str}"
    intro_path = str(work_dir / "intro.mp4")
    if _make_title_card(intro_path, intro_text, duration=3, color="black"):
        processed_clips.append(intro_path)
    else:
        logger.warning("Intro card generation failed — skipping intro")

    # --- Content clips (already composited with overlays) ---
    for i, clip in enumerate(clips):
        clip_path = clip["path"]
        if os.path.exists(clip_path):
            processed_clips.append(clip_path)
        else:
            logger.warning("Clip %d not found at %s — skipping", i, clip_path)

    # --- Outro card ---
    outro_text = "END TRANSMISSION // UNCLASSIFIED\nORTHANC OSINT PLATFORM"
    outro_path = str(work_dir / "outro.mp4")
    if _make_title_card(outro_path, outro_text, duration=3, color="black"):
        processed_clips.append(outro_path)
    else:
        logger.warning("Outro card generation failed — skipping outro")

    if not processed_clips:
        logger.error("No clips to stitch")
        return str(Path(output_path).parent)

    # --- Write concat list ---
    concat_list_path = str(work_dir / "concat_list.txt")
    with open(concat_list_path, "w") as f:
        for clip_path in processed_clips:
            safe_path = clip_path.replace("'", r"\'")
            f.write(f"file '{safe_path}'\n")

    # --- Concatenate with re-encode (clips have mixed codecs/audio streams) ---
    logger.info("Stitching %d clips → %s", len(processed_clips), output_path)
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
    ]

    try:
        result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("ffmpeg concat failed:\n%s", result.stderr[-500:])
            return str(work_dir)
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg concat timed out")
        return str(work_dir)
    except Exception as exc:
        logger.error("ffmpeg concat error: %s", exc)
        return str(work_dir)

    logger.info("Stitched video saved → %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Step 7: Main orchestrator
# ---------------------------------------------------------------------------


async def generate_anime_brief(
    gemini_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    max_scenes: int = 6,
    brief_id: str | None = None,
) -> str | None:
    """
    Generate a 90s cyberpunk anime intelligence briefing video.

    Pipeline:
      1. Fetch latest intelligence brief from DB
      2. Split executive summary into sentences
      3. LLM converts sentences into cyberpunk scene prompts
      4. Veo 3 generates video clips with native ambient audio
      5. Gemini native audio generates voiceover narration
      6. ffmpeg composites each clip (video + ambient + voiceover + overlay)
      7. ffmpeg stitches all clips with intro/outro cards

    Returns the path to the output MP4, or None if generation failed.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(OUTPUT_BASE, timestamp)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Anime brief output dir: %s", output_dir)

    gem_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
    or_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")

    # Step 1: Fetch latest brief
    logger.info("Fetching latest intelligence brief from DB...")
    brief = await fetch_latest_brief(brief_id=brief_id)
    if not brief or not brief["executive_summary"]:
        logger.error("No brief found or empty executive summary")
        return None

    logger.info(
        "Using brief from %s (%d posts, %dh window)",
        brief["generated_at"], brief["post_count"], brief["hours"]
    )

    # Step 2: Split into sentences
    sentences = split_into_sentences(brief["executive_summary"])
    sentences = sentences[:max_scenes]
    logger.info("Split executive summary into %d sentences", len(sentences))

    if not sentences:
        logger.error("No sentences extracted from executive summary")
        return None

    # Step 3: Generate scene prompts
    if or_key:
        scenes = await generate_scene_prompts(sentences, or_key)
    else:
        logger.warning("No OPENROUTER_API_KEY — using fallback scene prompts")
        scenes = _fallback_scene_prompts(sentences)

    if not scenes:
        logger.error("No scene prompts generated")
        return None

    logger.info("Generated %d scene prompts", len(scenes))

    # Steps 4 & 5: Generate video clips and voiceovers, then composite
    clips: list[dict] = []

    for i, scene in enumerate(scenes):
        video_path = os.path.join(output_dir, f"scene_{i:02d}.mp4")
        voiceover_path = os.path.join(output_dir, f"voiceover_{i:02d}.wav")
        composite_path = os.path.join(output_dir, f"composite_{i:02d}.mp4")

        narration = scene.get("narration_text", "")
        video_prompt = scene.get("video_prompt", "")
        overlay = scene.get("overlay_text", "")

        logger.info("Scene %d/%d: %s", i + 1, len(scenes), overlay)

        # Step 4: Generate video (Gemini Veo 3 primary, OpenRouter fallback)
        video_ok = False
        if gem_key and video_prompt:
            try:
                video_ok = await generate_video_clip_gemini(video_prompt, video_path, gem_key)
            except Exception as exc:
                logger.error("Veo 3 unhandled error for scene %d: %s", i + 1, exc, exc_info=True)

        if not video_ok and or_key and video_prompt:
            logger.info("Veo 3 failed for scene %d — trying OpenRouter fallback", i + 1)
            try:
                video_ok = await generate_video_clip_openrouter(video_prompt, video_path, or_key)
            except Exception as exc:
                logger.error("OpenRouter video unhandled error for scene %d: %s", i + 1, exc, exc_info=True)

        if not video_ok:
            logger.warning("Video generation failed for scene %d — skipping", i + 1)
            continue

        # Step 5: Generate voiceover
        voiceover_ok = False
        if gem_key and narration:
            try:
                voiceover_ok = await generate_voiceover(narration, voiceover_path, gem_key)
            except Exception as exc:
                logger.error("Voiceover unhandled error for scene %d: %s", i + 1, exc, exc_info=True)

        # Step 6: Composite video + voiceover + overlay
        if voiceover_ok:
            composite_ok = _composite_clip(video_path, voiceover_path, composite_path, overlay)
            if not composite_ok:
                logger.warning("Composite failed for scene %d — using raw video", i + 1)
        else:
            logger.info("No voiceover for scene %d — adding text overlay only", i + 1)
            _add_text_overlay(video_path, composite_path, overlay)

        final_clip_path = composite_path if os.path.exists(composite_path) else video_path

        clips.append({
            "path": final_clip_path,
            "overlay_text": overlay,
            "narrative_title": overlay,
        })
        logger.info("✓ Scene %d complete: %s", i + 1, final_clip_path)

    if not clips:
        logger.error("No clips generated — cannot produce anime brief")
        return None

    logger.info("%d/%d scenes generated successfully", len(clips), len(scenes))

    # Step 7: Stitch all clips together
    final_path = os.path.join(output_dir, "anime_brief.mp4")
    result_path = await stitch_clips(clips, final_path, title="INTELLIGENCE BRIEF // CLASSIFIED")

    logger.info("Anime brief complete: %s (%d scenes)", result_path, len(clips))
    return result_path
