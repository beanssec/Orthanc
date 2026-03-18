"""Cost estimation for LLM API calls.

Simple per-model cost tables for calculating estimated USD cost from token usage.
Costs are approximate and may drift from actual provider pricing — treat as estimates.
"""

from __future__ import annotations

# Cost per 1M tokens, keyed by lowercase model identifier fragment.
# (input_per_1m_usd, output_per_1m_usd)
# Match order: longest-matching substring wins.
_COST_TABLE: list[tuple[str, float, float]] = [
    # OpenAI
    ("gpt-4o-mini",               0.15,   0.60),
    ("gpt-4o",                    2.50,  10.00),
    ("gpt-4-turbo",               10.0,  30.00),
    ("gpt-4",                     30.0,  60.00),
    ("gpt-3.5-turbo",             0.50,   1.50),
    # Anthropic
    ("claude-opus",               15.0,  75.00),
    ("claude-sonnet-4-5",          3.0,  15.00),
    ("claude-sonnet-4",            3.0,  15.00),
    ("claude-sonnet",              3.0,  15.00),
    ("claude-haiku",               0.25,  1.25),
    # xAI / Grok
    ("grok-3-mini",                0.0,   0.0),   # free tier / unknown
    ("grok-3",                     0.0,   0.0),   # free tier / unknown
    ("grok-2-vision",              2.0,  10.0),
    ("grok-2",                     2.0,  10.0),
    ("grok",                       0.0,   0.0),
    # Embeddings
    ("text-embedding-3-small",     0.02,  0.0),
    ("text-embedding-3-large",     0.13,  0.0),
    ("text-embedding-ada-002",     0.10,  0.0),
    # Llama / Ollama (self-hosted = free)
    ("llama",                      0.0,   0.0),
    ("mistral",                    0.0,   0.0),
    ("nomic-embed",                0.0,   0.0),
]

# Sentinel cost for "unknown model"
_UNKNOWN_COST = (None, None)


def estimate_cost(
    model_id: str,
    tokens_in: int,
    tokens_out: int,
) -> float | None:
    """Return estimated USD cost for a call, or None if model is unknown.

    Args:
        model_id:   Provider model identifier (e.g. "openai/gpt-4o-mini").
        tokens_in:  Input / prompt token count.
        tokens_out: Output / completion token count.

    Returns:
        Estimated cost in USD, or None if no pricing data is available.
    """
    key = model_id.lower()

    # Strip namespace prefix (e.g. "openai/gpt-4o-mini" → "gpt-4o-mini")
    if "/" in key:
        key = key.split("/", 1)[1]

    matched_input: float | None = None
    matched_output: float | None = None
    best_len = 0

    for fragment, input_cost, output_cost in _COST_TABLE:
        if fragment in key and len(fragment) > best_len:
            matched_input = input_cost
            matched_output = output_cost
            best_len = len(fragment)

    if matched_input is None:
        return None

    cost = (tokens_in / 1_000_000) * matched_input + (tokens_out / 1_000_000) * matched_output
    return round(cost, 8)


def get_model_rates(model_id: str) -> tuple[float | None, float | None]:
    """Return (input_per_1m_usd, output_per_1m_usd) for a model, or (None, None)."""
    key = model_id.lower()
    if "/" in key:
        key = key.split("/", 1)[1]

    best_len = 0
    result = _UNKNOWN_COST
    for fragment, input_cost, output_cost in _COST_TABLE:
        if fragment in key and len(fragment) > best_len:
            result = (input_cost, output_cost)
            best_len = len(fragment)

    return result
