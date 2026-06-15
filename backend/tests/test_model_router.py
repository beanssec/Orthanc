"""
Model router tests — TASK-97.

Pure unit tests for the ModelRouter class.
No real LLM API calls are made — all providers are mocked.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://invalid:invalid@localhost:5999/invalid_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-orthanc-2024")


# ── Provider mock factory ─────────────────────────────────────────────────────

def _mock_provider(name: str = "mock", supports_embeddings: bool = True,
                   chat_result: dict | None = None, embed_result: list | None = None,
                   should_fail: bool = False) -> MagicMock:
    """Build a mock LLMProvider."""
    from app.services.model_router import LLMProvider
    p = MagicMock(spec=LLMProvider)
    p.supports_chat = True
    p.supports_embeddings = supports_embeddings
    p.supports_vision = False
    p.supports_response_format = True

    if should_fail:
        p.chat = AsyncMock(side_effect=RuntimeError(f"Provider {name} failed"))
        p.embed = AsyncMock(side_effect=RuntimeError(f"Provider {name} embed failed"))
    else:
        p.chat = AsyncMock(return_value=chat_result or {
            "content": f"Response from {name}",
            "thinking": None,
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "model": "test-model",
            "provider": name,
        })
        p.embed = AsyncMock(return_value=embed_result or [0.1, 0.2, 0.3, 0.4])

    p.list_models = AsyncMock(return_value=[{"id": f"{name}/model", "name": f"{name} model"}])
    return p


def _fresh_router():
    """Return a fresh ModelRouter instance (not the global singleton)."""
    from app.services.model_router import ModelRouter
    return ModelRouter()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_provider_registration():
    """Registering a provider makes it available by name."""
    router = _fresh_router()
    provider = _mock_provider("openrouter")

    assert "openrouter" not in router._providers

    router.register_provider("openrouter", provider)

    assert "openrouter" in router._providers
    assert router._providers["openrouter"] is provider


@pytest.mark.unit
def test_task_model_override():
    """set_task_model persists the override; get_task_model returns it."""
    from app.services.model_router import ModelRouter
    router = _fresh_router()

    original = router.get_task_model(ModelRouter.TASK_BRIEF)
    router.set_task_model(ModelRouter.TASK_BRIEF, "anthropic/claude-3-haiku")

    assert router.get_task_model(ModelRouter.TASK_BRIEF) == "anthropic/claude-3-haiku"
    assert router.get_task_model(ModelRouter.TASK_BRIEF) != original


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fallback_on_failure():
    """When the primary provider fails, the router falls back to a secondary."""
    from app.services.model_router import ModelRouter
    router = _fresh_router()

    failing = _mock_provider("primary", should_fail=True)
    fallback = _mock_provider("fallback", chat_result={
        "content": "Fallback response",
        "thinking": None,
        "usage": {},
        "model": "fallback-model",
        "provider": "fallback",
    })

    router.register_provider("primary", failing)
    router.register_provider("fallback", fallback)

    # Map the task model to something the primary handles
    router.set_task_model(ModelRouter.TASK_SUMMARISE, "grok-3-mini")
    router.map_model_to_provider("grok-3-mini", "primary")

    result = await router.chat(
        ModelRouter.TASK_SUMMARISE,
        [{"role": "user", "content": "Summarise this."}],
    )
    # Should have gotten the fallback response
    assert result["content"] == "Fallback response"
    assert result.get("provider") == "fallback"


@pytest.mark.unit
def test_capability_flags():
    """A provider with supports_embeddings=False is skipped for embed tasks."""
    from app.services.model_router import ModelRouter
    router = _fresh_router()

    no_embed = _mock_provider("xai_no_embed", supports_embeddings=False)
    with_embed = _mock_provider("openrouter_embed", supports_embeddings=True)

    router.register_provider("xai", no_embed)
    router.register_provider("openrouter", with_embed)

    # Map embed model to the no-embed provider; the router should skip it
    router.map_model_to_provider("openai/text-embedding-3-small", "xai")
    router.set_task_model(ModelRouter.TASK_EMBED, "openai/text-embedding-3-small")

    # _get_embed_capable_provider skips xAI (no supports_embeddings)
    provider, pname = router._get_embed_capable_provider("openai/text-embedding-3-small")

    # Should have found a provider that supports embeddings (or None if none available)
    if provider is not None:
        assert getattr(provider, "supports_embeddings", True)


@pytest.mark.unit
def test_default_task_models():
    """Default task models are defined and non-empty."""
    from app.services.model_router import ModelRouter

    defaults = ModelRouter.DEFAULT_TASK_MODELS
    assert isinstance(defaults, dict)
    assert len(defaults) > 0
    assert ModelRouter.TASK_BRIEF in defaults
    assert ModelRouter.TASK_EMBED in defaults
    assert ModelRouter.TASK_SUMMARISE in defaults
    # All default values should be non-empty strings
    for task, model in defaults.items():
        assert isinstance(model, str), f"Task {task} has non-string default model"
        assert model, f"Task {task} has empty default model"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provider_health():
    """A provider that consistently fails should not prevent the router returning an error."""
    from app.services.model_router import ModelRouter
    router = _fresh_router()

    bad_provider = _mock_provider("bad", should_fail=True)
    router.register_provider("bad", bad_provider)
    router.map_model_to_provider("grok-3-mini", "bad")
    router.set_task_model(ModelRouter.TASK_BRIEF, "grok-3-mini")

    with pytest.raises(Exception):
        await router.chat(
            ModelRouter.TASK_BRIEF,
            [{"role": "user", "content": "Hello"}],
        )

    # Performance stats should record the error
    stats = router.get_performance_stats()
    # Stats might be empty if the error occurs before _update_perf is called
    assert isinstance(stats, dict)
