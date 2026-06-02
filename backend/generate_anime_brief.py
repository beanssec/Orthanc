#!/usr/bin/env python3
"""
CLI runner for generating 90s cyberpunk anime intelligence brief videos.

Pipeline:
  1. Pull latest intelligence brief from the `briefs` DB table
  2. Extract executive_summary and split into individual sentences
  3. LLM converts each sentence into a cyberpunk anime scene prompt (with audio cues)
  4. Veo 3 generates each video clip WITH native ambient audio
  5. Gemini native audio generates voiceover narration for each sentence
  6. ffmpeg composites: video + ambient audio + voiceover + text overlay
  7. ffmpeg stitches all clips with intro/outro cards

Usage:
  # Full video generation (needs GEMINI_API_KEY and/or OPENROUTER_API_KEY)
  python generate_anime_brief.py

  # Dry run — fetch brief and generate prompts only (no video)
  python generate_anime_brief.py --dry-run

  # Limit scene count
  python generate_anime_brief.py --scenes 3

  # Use a specific brief by ID instead of latest
  python generate_anime_brief.py --brief-id 42

  # Pass API keys directly
  python generate_anime_brief.py --gemini-key sk-... --openrouter-key sk-or-...

Requirements:
  pip install google-genai httpx sqlalchemy asyncpg

ffmpeg:
  Required for stitching clips into a single MP4.
  Install: apt-get install ffmpeg
  Or add to Dockerfile: RUN apt-get update && apt-get install -y ffmpeg
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Allow running from the backend/ directory without installing the package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-35s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("generate_anime_brief")


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate 90s cyberpunk anime intelligence brief video",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--scenes",
        type=int,
        default=6,
        help="Max number of scenes (sentences) to visualize (default: 6)",
    )
    parser.add_argument(
        "--brief-id",
        default=None,
        help="Use a specific brief by ID instead of the latest",
    )
    parser.add_argument(
        "--openrouter-key",
        default=None,
        help="OpenRouter API key (or set OPENROUTER_API_KEY env var)",
    )
    parser.add_argument(
        "--gemini-key",
        default=None,
        help="Gemini API key (or set GEMINI_API_KEY env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch brief and generate scene prompts only — no video generation",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


async def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Import after path setup
    try:
        from app.services.anime_brief_generator import (  # type: ignore[import]
            fetch_latest_brief,
            generate_anime_brief,
            generate_scene_prompts,
            split_into_sentences,
            _fallback_scene_prompts,
        )
    except ImportError as exc:
        logger.error(
            "Failed to import anime_brief_generator: %s\n"
            "Make sure you're running from the backend/ directory "
            "and all dependencies are installed.",
            exc,
        )
        return 1

    # ------------------------------------------------------------------ #
    # DRY RUN — show brief summary and generated scene prompts            #
    # ------------------------------------------------------------------ #
    if args.dry_run:
        logger.info("=== DRY RUN MODE ===")
        logger.info("Fetching latest intelligence brief from DB...")

        brief = await fetch_latest_brief(brief_id=args.brief_id)

        if not brief:
            print("\n⚠  No brief found in the database.\n")
            return 0

        summary = brief.get("executive_summary", "")
        if not summary:
            print("\n⚠  Brief found but executive_summary is empty.\n")
            return 0

        print(f"\n📋  Brief ID: {brief['id']}")
        print(f"    Generated: {brief['generated_at']}")
        print(f"    Window:    {brief['hours']}h | Posts: {brief['post_count']}")
        print(f"\n📝  Executive Summary:\n")
        print(f"    {summary[:500]}{'...' if len(summary) > 500 else ''}\n")

        sentences = split_into_sentences(summary)[: args.scenes]
        print(f"Split into {len(sentences)} sentence(s):\n")
        for i, s in enumerate(sentences, 1):
            print(f"  {i}. {s}")
        print()

        or_key = args.openrouter_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not or_key:
            print(
                "⚠  OPENROUTER_API_KEY not set — showing fallback scene prompts.\n"
                "   Set the env var or pass --openrouter-key to use the LLM.\n"
            )
            scenes = _fallback_scene_prompts(sentences)
        else:
            print("Generating scene prompts via OpenRouter...\n")
            scenes = await generate_scene_prompts(sentences, or_key)

        if not scenes:
            print("❌  Scene prompt generation returned no results.\n")
            return 1

        print(f"Generated {len(scenes)} scene prompt(s):\n")
        for s in scenes:
            print(f"  Scene {s.get('scene_number', '?')}")
            print(f"    Narration : {s.get('narration_text', '')[:100]}")
            print(f"    Prompt    : {s.get('video_prompt', '')[:120]}...")
            print(f"    Overlay   : {s.get('overlay_text', '')}")
            print()

        return 0

    # ------------------------------------------------------------------ #
    # FULL RUN — generate video                                           #
    # ------------------------------------------------------------------ #
    or_key = args.openrouter_key or os.environ.get("OPENROUTER_API_KEY", "")
    gem_key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")

    if not gem_key:
        logger.warning(
            "GEMINI_API_KEY not set — Veo 3 video generation and voiceover will be unavailable. "
            "Video generation will fall back to OpenRouter experimental models."
        )
    if not or_key:
        logger.warning(
            "OPENROUTER_API_KEY not set — scene prompts will use fallback templates "
            "and OpenRouter video models will be unavailable."
        )
    if not or_key and not gem_key:
        logger.error(
            "No API keys available. Set GEMINI_API_KEY (recommended) and/or OPENROUTER_API_KEY."
        )
        return 1

    logger.info(
        "Starting anime brief generation: max %d scenes, brief_id=%s",
        args.scenes,
        args.brief_id or "latest",
    )

    result = await generate_anime_brief(
        gemini_api_key=gem_key or None,
        openrouter_api_key=or_key or None,
        max_scenes=args.scenes,
        brief_id=args.brief_id,
    )

    if result:
        print(f"\n✅  Anime brief generated: {result}\n")
        return 0
    else:
        print("\n❌  Failed to generate anime brief. Check logs above for details.\n")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
