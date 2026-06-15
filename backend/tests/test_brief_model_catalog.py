from __future__ import annotations

import pytest

import uuid
from unittest.mock import MagicMock


def make_user():
    user = MagicMock()
    user.id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    user.username = "testuser"
    return user


@pytest.mark.unit
def test_merge_brief_models_refreshes_static_context_and_appends_live_models():
    from app.services.ai_models import merge_brief_models

    live = [
        {
            "id": "google/gemini-2.5-flash",
            "provider": "openrouter",
            "name": "Live Gemini Flash",
            "description": "live desc",
            "strengths": "",
            "context_window": 1_048_576,
            "max_completion_tokens": 65_536,
            "cost_per_1k_input": 0.0003,
            "cost_per_1k_output": 0.0025,
            "cost_estimate_per_brief": "~$0.075",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "credential_provider": "openrouter",
            "key_field": "api_key",
            "_live": True,
        },
        {
            "id": "openai/gpt-5.5",
            "provider": "openrouter",
            "name": "OpenAI: GPT-5.5",
            "description": "New live OpenRouter model.",
            "strengths": "",
            "context_window": 1_050_000,
            "max_completion_tokens": 128_000,
            "cost_per_1k_input": 0.005,
            "cost_per_1k_output": 0.03,
            "cost_estimate_per_brief": "~$0.900",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "credential_provider": "openrouter",
            "key_field": "api_key",
            "_live": True,
        },
    ]

    merged = merge_brief_models(live, {"openrouter"})
    by_id = {m["id"]: m for m in merged}

    assert by_id["google/gemini-2.5-flash"]["context_window"] == 1_048_576
    assert by_id["google/gemini-2.5-flash"]["max_completion_tokens"] == 65_536
    # Curated copy should remain, while volatile provider data is refreshed.
    assert "massive 1M context" in by_id["google/gemini-2.5-flash"]["description"]
    assert by_id["google/gemini-2.5-flash"]["available"] is True

    assert by_id["openai/gpt-5.5"]["name"] == "OpenAI: GPT-5.5"
    assert by_id["openai/gpt-5.5"]["context_window"] == 1_050_000
    assert by_id["openai/gpt-5.5"]["available"] is True


@pytest.mark.unit
def test_large_context_budget_uses_far_more_posts_than_legacy_bucket():
    from app.services.brief_generator import estimate_brief_context_budget

    budget_128k = estimate_brief_context_budget(128_000, 16_384)
    budget_1m = estimate_brief_context_budget(1_050_000, 128_000)

    assert budget_1m["max_posts"] > 500
    assert budget_1m["max_chars_per_post"] >= 1_600
    assert budget_1m["target_input_tokens"] > 800_000
    assert budget_1m["max_posts"] > budget_128k["max_posts"]


@pytest.mark.unit
def test_temporal_sampling_plan_scales_without_legacy_48_post_cap():
    from app.services.brief_post_selector import _compute_temporal_sampling_plan

    small = _compute_temporal_sampling_plan(remaining=48, hours=24)
    large = _compute_temporal_sampling_plan(remaining=900, hours=72)

    assert small.posts_per_slice == 2
    assert small.n_slices == 24
    assert large.posts_per_slice == 4
    assert large.n_slices > 48
    assert large.n_slices <= 168
    assert large.slice_seconds > 0


@pytest.mark.unit
def test_add_selection_deduplicates_and_enforces_budget():
    from app.services.brief_post_selector import _add_selection

    class PostStub:
        def __init__(self, post_id: str):
            self.id = post_id

    selected = []
    selected_ids = set()
    first = PostStub("post-1")
    second = PostStub("post-2")

    assert _add_selection(
        selected,
        selected_ids,
        first,
        reason="ALERT: test",
        tier=1,
        priority_score=1.0,
        budget=2,
    ) is True
    assert _add_selection(
        selected,
        selected_ids,
        first,
        reason="duplicate",
        tier=5,
        priority_score=0.1,
        budget=2,
    ) is False
    assert _add_selection(
        selected,
        selected_ids,
        second,
        reason="TEMPORAL: test",
        tier=5,
        priority_score=0.5,
        budget=1,
    ) is False

    assert selected == [
        {
            "post": first,
            "selection_reason": "ALERT: test",
            "tier": 1,
            "priority_score": 1.0,
        }
    ]
    assert selected_ids == {"post-1"}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_brief_models_endpoint_fetches_public_openrouter_catalog_without_key(monkeypatch):
    from app.routers import briefs

    async def fake_get_keys(user_id: str, provider: str):
        return None

    async def fake_fetch(api_key: str = ""):
        assert api_key == ""
        return [
            {
                "id": "openai/gpt-5.5",
                "provider": "openrouter",
                "name": "OpenAI: GPT-5.5",
                "description": "Current live model.",
                "strengths": "",
                "context_window": 1_050_000,
                "max_completion_tokens": 128_000,
                "cost_per_1k_input": 0.005,
                "cost_per_1k_output": 0.03,
                "cost_estimate_per_brief": "~$0.900",
                "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                "credential_provider": "openrouter",
                "key_field": "api_key",
                "_live": True,
            }
        ]

    cached: list[list[dict]] = []
    monkeypatch.setattr(briefs.collector_manager, "get_keys", fake_get_keys)
    monkeypatch.setattr(briefs, "fetch_live_openrouter_models", fake_fetch)
    monkeypatch.setattr(briefs, "cache_live_models", lambda models: cached.append(models))

    result = await briefs.list_models(current_user=make_user())
    by_id = {m["id"]: m for m in result}

    assert by_id["openai/gpt-5.5"]["context_window"] == 1_050_000
    assert by_id["openai/gpt-5.5"]["available"] is False
    assert by_id["openai/gpt-5.5"]["requires"] == "openrouter"
    assert cached and cached[0][0]["id"] == "openai/gpt-5.5"
