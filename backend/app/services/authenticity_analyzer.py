"""AI-powered image authenticity analysis using vision-capable LLMs."""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger("orthanc.services.authenticity")

ANALYSIS_PROMPT = """Analyze this image for signs of AI generation or digital manipulation. Consider:

1. **Visual artifacts**: Warped/inconsistent text, impossible geometry, melted or extra fingers/hands, asymmetric facial features, texture irregularities, unnatural skin, hair blending issues
2. **Lighting & shadows**: Inconsistent light sources, impossible shadows, overexposed highlights common in AI renders
3. **Too perfect**: Unnaturally clean scenes, idealized faces, suspiciously uniform backgrounds
4. **Metadata**: I will provide any EXIF data found (or note if it was stripped — stripping is suspicious)
5. **Context**: This image came from a Telegram OSINT channel monitoring conflict/geopolitical events

Respond ONLY with valid JSON in this exact format (no markdown, no extra text):
{
    "score": 0.85,
    "verdict": "likely_real",
    "confidence": "high",
    "reasoning": "Brief 1-2 sentence explanation of key observations",
    "indicators": {
        "ai_artifacts": false,
        "metadata_suspicious": false,
        "inconsistent_lighting": false,
        "text_anomalies": false,
        "anatomical_errors": false,
        "too_perfect": false
    }
}

score: 0.0 = definitely AI generated/manipulated, 1.0 = definitely authentic photograph
verdict: exactly one of "likely_real", "uncertain", "likely_ai", "confirmed_ai"
confidence: exactly one of "high", "medium", "low"
"""

# Media dir for reading files (matches media_service.py)
MEDIA_DIR = "/app/data/media"


class AuthenticityAnalyzer:
    """Analyzes media authenticity using vision-capable LLMs."""

    async def analyze_image(
        self,
        relative_path: str,
        metadata: dict,
        api_key: str,
        provider: str = "xai",   # "xai" or "openrouter"
    ) -> Optional[dict]:
        """
        Send image to a vision LLM for AI-generation analysis.

        Args:
            relative_path: Path relative to MEDIA_DIR
            metadata: EXIF/file metadata dict from MediaService
            api_key: Provider API key
            provider: "xai" (Grok) or "openrouter" (GPT-4o)

        Returns:
            Parsed result dict or None on failure.
        """
        import os
        abs_path = os.path.join(MEDIA_DIR, relative_path)

        try:
            with open(abs_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as exc:
            logger.error("Cannot read image for analysis %s: %s", abs_path, exc)
            return None

        # Build metadata context string
        meta_context = _build_meta_context(metadata)
        prompt = ANALYSIS_PROMPT + meta_context

        # Detect MIME type from extension
        ext = relative_path.rsplit(".", 1)[-1].lower()
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        mime = mime_map.get(ext, "image/jpeg")

        # xAI only supports vision on specific tier keys — use openrouter/gpt-4o if available
        if provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            model = "openai/gpt-4o"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://orthanc.local",
                "X-Title": "Orthanc OSINT",
            }
        else:  # xai
            url = "https://api.x.ai/v1/chat/completions"
            model = "grok-2-vision-1212"  # legacy alias, most widely available
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_data}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 600,
            "temperature": 0.1,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            content: str = data["choices"][0]["message"]["content"]
            return _parse_json_response(content)

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Authenticity API error (%s %s): %s",
                provider, exc.response.status_code, exc.response.text[:200]
            )
            return None
        except Exception as exc:
            logger.error("Authenticity analysis failed (%s): %s", relative_path, exc)
            return None


def _build_meta_context(metadata: dict) -> str:
    """Build a human-readable metadata context string for the prompt."""
    if not metadata:
        return ""
    parts: list[str] = []
    exif = metadata.get("exif")
    if exif:
        parts.append(f"\nEXIF data found: {json.dumps(exif)}")
    elif metadata.get("exif_stripped"):
        parts.append(
            "\nNote: EXIF data has been completely stripped from this image. "
            "This is suspicious and common with manipulated/AI-generated images shared online."
        )
    if metadata.get("ai_software_detected"):
        parts.append(
            f"\nWARNING: AI generation software detected in EXIF: "
            f"{metadata.get('ai_software_name', 'unknown')}"
        )
    dims = ""
    if metadata.get("width") and metadata.get("height"):
        dims = f"{metadata['width']}×{metadata['height']}"
    if dims:
        parts.append(f"\nImage dimensions: {dims}")
    return "".join(parts)


def _parse_json_response(content: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown code fences."""
    content = content.strip()
    # Strip markdown fences if present
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0]
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse authenticity JSON: %s | content: %s", exc, content[:300])
        return None


authenticity_analyzer = AuthenticityAnalyzer()
