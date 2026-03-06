"""AI model registry with descriptions and pricing for intelligence briefs."""
from __future__ import annotations

AI_MODELS = [
    {
        "id": "grok-3-mini",
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
        "id": "anthropic/claude-sonnet-4-20250514",
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
        "id": "anthropic/claude-haiku-3.5",
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
        "id": "google/gemini-2.5-flash-preview",
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
        "id": "meta-llama/llama-3.3-70b-instruct",
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
