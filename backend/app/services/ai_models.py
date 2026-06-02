"""AI model registry with descriptions and pricing for intelligence briefs."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("orthanc.ai_models")

AI_MODELS = [
    {
        "id": "grok-3-mini",
        "max_completion_tokens": 8192,
        "provider": "xai",
        "name": "Grok 3 Mini",
        "description": "Fast and affordable. Good for routine daily briefs and quick summaries.",
        "strengths": "Speed, low cost, real-time X/Twitter awareness",
        "context_window": 131072,
        "cost_per_1k_input": 0.0003,
        "cost_per_1k_output": 0.0005,
        "cost_estimate_per_brief": "~$0.01",
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "credential_provider": "x",
        "key_field": "api_key",
    },
    {
        "id": "grok-3",
        "max_completion_tokens": 8192,
        "provider": "xai",
        "name": "Grok 3",
        "description": "More capable than Mini. Better reasoning for complex geopolitical analysis.",
        "strengths": "Deep analysis, nuanced reasoning, X/Twitter integration",
        "context_window": 131072,
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
        "cost_estimate_per_brief": "~$0.10",
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "credential_provider": "x",
        "key_field": "api_key",
    },
    {
        "id": "anthropic/claude-sonnet-4",
        "max_completion_tokens": 4096,
        "provider": "openrouter",
        "name": "Claude Sonnet 4",
        "description": "Excellent analytical reasoning. Best for nuanced intelligence reports with careful hedging.",
        "strengths": "Nuanced analysis, long context, careful reasoning, low hallucination",
        "context_window": 200000,
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
        "cost_estimate_per_brief": "~$0.08",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "anthropic/claude-3.5-haiku",
        "max_completion_tokens": 4096,
        "provider": "openrouter",
        "name": "Claude Haiku 3.5",
        "description": "Fast and cheap. Good balance of quality and speed for frequent briefs.",
        "strengths": "Speed, low cost, solid reasoning",
        "context_window": 200000,
        "cost_per_1k_input": 0.0008,
        "cost_per_1k_output": 0.004,
        "cost_estimate_per_brief": "~$0.02",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "openai/gpt-4o",
        "max_completion_tokens": 4096,
        "provider": "openrouter",
        "name": "GPT-4o",
        "description": "OpenAI's flagship. Strong all-rounder for general intelligence analysis.",
        "strengths": "Broad knowledge, reliable formatting, good at structured output",
        "context_window": 128000,
        "cost_per_1k_input": 0.0025,
        "cost_per_1k_output": 0.01,
        "cost_estimate_per_brief": "~$0.06",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "openai/gpt-4o-mini",
        "max_completion_tokens": 4096,
        "provider": "openrouter",
        "name": "GPT-4o Mini",
        "description": "Budget-friendly OpenAI model. Decent quality at very low cost.",
        "strengths": "Very cheap, fast, adequate for simple summaries",
        "context_window": 128000,
        "cost_per_1k_input": 0.00015,
        "cost_per_1k_output": 0.0006,
        "cost_estimate_per_brief": "~$0.005",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "google/gemini-2.5-flash",
        "max_completion_tokens": 8192,
        "provider": "openrouter",
        "name": "Gemini 2.5 Flash",
        "description": "Google's fast model with massive 1M context. Can process far more posts per brief.",
        "strengths": "Huge context window, fast, good for bulk analysis",
        "context_window": 1000000,
        "cost_per_1k_input": 0.00015,
        "cost_per_1k_output": 0.0006,
        "cost_estimate_per_brief": "~$0.005",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "mistralai/mistral-large-2411",
        "max_completion_tokens": 4096,
        "provider": "openrouter",
        "name": "Mistral Large",
        "description": "Strong multilingual model. Best for analyzing non-English OSINT sources.",
        "strengths": "Multilingual analysis, European/Arabic content, good reasoning",
        "context_window": 128000,
        "cost_per_1k_input": 0.002,
        "cost_per_1k_output": 0.006,
        "cost_estimate_per_brief": "~$0.04",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "openai/gpt-5.4-nano",
        "max_completion_tokens": 8192,
        "provider": "openrouter",
        "name": "GPT-5.4 Nano",
        "description": "Ultra-fast, ultra-cheap. Excellent for structured extraction, classification, and high-volume tasks.",
        "strengths": "Speed, low cost, strong JSON output, good reasoning for its size",
        "context_window": 400000,
        "cost_per_1k_input": 0.0002,
        "cost_per_1k_output": 0.00125,
        "cost_estimate_per_brief": "~$0.01",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "openai/gpt-5.4-mini",
        "max_completion_tokens": 16384,
        "provider": "openrouter",
        "name": "GPT-5.4 Mini",
        "description": "Strong reasoning at moderate cost. Ideal for analytical tasks requiring judgment.",
        "strengths": "Solid reasoning, fast, good at synthesis and nuanced analysis",
        "context_window": 400000,
        "cost_per_1k_input": 0.00075,
        "cost_per_1k_output": 0.0045,
        "cost_estimate_per_brief": "~$0.04",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "openai/gpt-5.4",
        "max_completion_tokens": 32768,
        "provider": "openrouter",
        "name": "GPT-5.4",
        "description": "OpenAI's flagship. Best-in-class for comprehensive intelligence analysis.",
        "strengths": "Deep reasoning, excellent synthesis, large context, best structured output",
        "context_window": 1050000,
        "cost_per_1k_input": 0.0025,
        "cost_per_1k_output": 0.015,
        "cost_estimate_per_brief": "~$0.15",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "google/gemini-2.5-flash-lite",
        "max_completion_tokens": 8192,
        "provider": "openrouter",
        "name": "Gemini 2.5 Flash Lite",
        "description": "Google's cheapest model. Fast for translation and simple tasks.",
        "strengths": "Extremely cheap, fast, good multilingual, 1M context",
        "context_window": 1048576,
        "cost_per_1k_input": 0.0001,
        "cost_per_1k_output": 0.0004,
        "cost_estimate_per_brief": "~$0.003",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "google/gemini-2.5-pro",
        "max_completion_tokens": 16384,
        "provider": "openrouter",
        "name": "Gemini 2.5 Pro",
        "description": "Google's best model. Massive context window with strong analytical capability.",
        "strengths": "1M context, deep reasoning, strong at long-document analysis",
        "context_window": 1048576,
        "cost_per_1k_input": 0.00125,
        "cost_per_1k_output": 0.01,
        "cost_estimate_per_brief": "~$0.08",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
    {
        "id": "x-ai/grok-4.20",
        "max_completion_tokens": 16384,
        "provider": "xai",
        "name": "Grok 4.20",
        "description": "xAI's flagship. Strong reasoning with real-time X/Twitter context.",
        "strengths": "Deep analysis, 2M context, real-time awareness, strong at geopolitics",
        "context_window": 2000000,
        "cost_per_1k_input": 0.002,
        "cost_per_1k_output": 0.006,
        "cost_estimate_per_brief": "~$0.06",
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "credential_provider": "x",
        "key_field": "api_key",
    },
    {
        "id": "x-ai/grok-4.1-fast",
        "max_completion_tokens": 16384,
        "provider": "xai",
        "name": "Grok 4.1 Fast",
        "description": "Fast and cheap xAI model. Good performance-to-dollar ratio.",
        "strengths": "Speed, 2M context, caching support, ~100 tok/s generation",
        "context_window": 2000000,
        "cost_per_1k_input": 0.0002,
        "cost_per_1k_output": 0.0005,
        "cost_estimate_per_brief": "~$0.005",
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "credential_provider": "x",
        "key_field": "api_key",
    },
    {
        "id": "meta-llama/llama-3.3-70b-instruct",
        "max_completion_tokens": 4096,
        "provider": "openrouter",
        "name": "Llama 3.3 70B",
        "description": "Open-source model via OpenRouter. Free tier available — good for testing.",
        "strengths": "Free/very cheap, decent quality, no vendor lock-in",
        "context_window": 131072,
        "cost_per_1k_input": 0.00018,
        "cost_per_1k_output": 0.00018,
        "cost_estimate_per_brief": "~$0.002",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    },
]


def get_model(model_id: str) -> dict | None:
    """Get model config by ID."""
    for m in AI_MODELS:
        if m["id"] == model_id:
            return m
    return None


def get_models_for_provider(provider: str) -> list[dict]:
    """Get all models available for a credential provider."""
    return [m for m in AI_MODELS if m["credential_provider"] == provider]


def get_available_models(configured_providers: set[str]) -> list[dict]:
    """Get models the user can actually use based on their configured credentials."""
    return [m for m in AI_MODELS if m["credential_provider"] in configured_providers]


# ---------------------------------------------------------------------------
# Live model fetching (OpenRouter)
# ---------------------------------------------------------------------------

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CHAT_MODALITIES = {"text->text", "text+image->text"}


async def fetch_live_openrouter_models(api_key: str) -> list[dict]:
    """Fetch the live model list from OpenRouter and return brief-friendly dicts.

    Only chat-capable models (text->text or text+image->text) are returned.
    Returns an empty list on any network / auth failure so callers degrade safely.
    """
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_OPENROUTER_MODELS_URL, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: list[dict] = []
        for m in data.get("data", []):
            arch = m.get("architecture", {})
            modality = arch.get("modality", "")
            if not any(cm in modality for cm in _CHAT_MODALITIES):
                continue

            pricing = m.get("pricing", {})
            try:
                cost_in = float(pricing.get("prompt", 0)) * 1000
            except (TypeError, ValueError):
                cost_in = 0.0
            try:
                cost_out = float(pricing.get("completion", 0)) * 1000
            except (TypeError, ValueError):
                cost_out = 0.0

            ctx = m.get("context_length") or 128000
            top_provider = m.get("top_provider") or {}
            max_comp = top_provider.get("max_completion_tokens") or min(16384, ctx // 4)
            results.append({
                "id": m["id"],
                "provider": "openrouter",
                "name": m.get("name", m["id"]),
                "description": m.get("description") or f"{m.get('name', m['id'])} via OpenRouter.",
                "strengths": "",
                "context_window": ctx,
                "max_completion_tokens": max_comp,
                "cost_per_1k_input": cost_in,
                "cost_per_1k_output": cost_out,
                "cost_estimate_per_brief": f"~${max(cost_in, cost_out) * 30:.3f}",
                "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                "credential_provider": "openrouter",
                "key_field": "api_key",
                "_live": True,
            })
        return results

    except Exception as exc:
        logger.warning("fetch_live_openrouter_models failed (non-fatal): %s", exc)
        return []


def merge_brief_models(
    live_openrouter: list[dict],
    configured_providers: set[str],
) -> list[dict]:
    """Merge static AI_MODELS registry with live OpenRouter models.

    Rules:
    - Static curated entries take precedence (richer metadata).
    - Live models not already in the registry are appended.
    - Availability flag is set based on configured_providers.
    - Each returned dict includes an ``available`` and ``requires`` key.
    """
    static_ids = {m["id"] for m in AI_MODELS}

    result: list[dict] = []

    # Static curated models first (full metadata)
    for m in AI_MODELS:
        result.append({
            **m,
            "available": m["credential_provider"] in configured_providers,
            "requires": m["credential_provider"],
        })

    # Append live-discovered models that are not already in the registry
    for m in live_openrouter:
        if m["id"] in static_ids:
            continue
        result.append({
            **m,
            "available": m["credential_provider"] in configured_providers,
            "requires": m["credential_provider"],
        })

    return result


# ---------------------------------------------------------------------------
# Live model cache — populated by fetch_live_openrouter_models / briefs router
# ---------------------------------------------------------------------------
_live_model_cache: dict[str, dict] = {}  # model_id -> model config


def cache_live_models(models: list[dict]) -> None:
    """Store live-fetched models so make_fallback_model_config can look them up."""
    for m in models:
        _live_model_cache[m["id"]] = m


def make_fallback_model_config(model_id: str) -> dict:
    """Return a model config for a model not in the static registry.

    Checks the live model cache first (populated from OpenRouter API),
    falls back to safe defaults if not cached.
    """
    # Check live cache for real context_window / pricing
    cached = _live_model_cache.get(model_id)
    if cached:
        logger.info(
            "Using cached live model config for %s (context_window=%d)",
            model_id, cached.get("context_window", 128000),
        )
        return {**cached}

    logger.info(
        "No cached config for model %s — using default 128K context_window",
        model_id,
    )
    return {
        "id": model_id,
        "provider": "openrouter",
        "name": model_id,
        "description": "Live OpenRouter model.",
        "strengths": "",
        "context_window": 128000,
        "max_completion_tokens": 16384,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "cost_estimate_per_brief": "unknown",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_provider": "openrouter",
        "key_field": "api_key",
    }
