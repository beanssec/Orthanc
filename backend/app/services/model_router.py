"""Unified LLM model router — routes AI tasks to configured providers."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger("orthanc.model_router")

# ---------------------------------------------------------------------------
# Base provider interface
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        """Send chat completion request.

        Returns:
            {"content": str, "usage": {"prompt_tokens": int, "completion_tokens": int}, "model": str}
        """

    @abstractmethod
    async def embed(self, text: str, model: str) -> list[float]:
        """Get embedding vector."""

    async def list_models(self) -> list[dict]:
        """List available models. Returns [{"id": str, "name": str}]"""
        return []


# ---------------------------------------------------------------------------
# OpenRouter provider
# ---------------------------------------------------------------------------

class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://openrouter.ai/api/v1"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        payload: dict[str, Any] = {"model": model, "messages": messages, **kwargs}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            r = await resp
            r.raise_for_status()
            data = r.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            "model": model,
        }

    async def embed(self, text: str, model: str = "openai/text-embedding-3-small") -> list[float]:
        payload = {"model": model, "input": text}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        return data["data"][0]["embedding"]

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                r.raise_for_status()
                data = r.json()
            models = []
            for m in data.get("data", []):
                # Only include chat-capable models (skip embedding-only)
                arch = m.get("architecture", {})
                modality = arch.get("modality", "")
                if "text->text" in modality or "text+image->text" in modality:
                    models.append({"id": m["id"], "name": m.get("name", m["id"]), "provider": "openrouter"})
            return models
        except Exception as exc:
            logger.warning("OpenRouter list_models failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# xAI / Grok provider
# ---------------------------------------------------------------------------

class XAIProvider(LLMProvider):
    """xAI/Grok API provider (OpenAI-compatible)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.x.ai/v1"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        payload: dict[str, Any] = {"model": model, "messages": messages, **kwargs}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            "model": model,
        }

    async def embed(self, text: str, model: str = "v1") -> list[float]:
        payload = {"model": model, "input": text}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        return data["data"][0]["embedding"]

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                r.raise_for_status()
                data = r.json()
            return [
                {"id": m["id"], "name": m.get("name", m["id"]), "provider": "xai"}
                for m in data.get("data", [])
            ]
        except Exception as exc:
            logger.warning("xAI list_models failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    """Ollama local/remote provider."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url.rstrip("/")

    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        payload = {"model": model, "messages": messages, "stream": False}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        content = data["message"]["content"]
        # Ollama may return prompt_eval_count / eval_count
        return {
            "content": content,
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            "model": model,
        }

    async def embed(self, text: str, model: str = "nomic-embed-text") -> list[float]:
        payload = {"model": model, "prompt": text}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/api/embeddings",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        return data["embedding"]

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                data = r.json()
            return [
                {"id": m["name"], "name": m["name"], "provider": "ollama"}
                for m in data.get("models", [])
            ]
        except Exception as exc:
            logger.warning("Ollama list_models failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (vLLM, llama.cpp, LM Studio, LocalAI…)
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(LLMProvider):
    """Any server implementing the OpenAI-compatible API."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        payload: dict[str, Any] = {"model": model, "messages": messages, **kwargs}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            "model": model,
        }

    async def embed(self, text: str, model: str = "") -> list[float]:
        payload: dict[str, Any] = {"input": text}
        if model:
            payload["model"] = model
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/v1/embeddings",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        return data["data"][0]["embedding"]

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                r.raise_for_status()
                data = r.json()
            return [
                {"id": m["id"], "name": m.get("name", m["id"]), "provider": "local"}
                for m in data.get("data", [])
            ]
        except Exception as exc:
            logger.warning("OpenAI-compatible list_models failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Model Router
# ---------------------------------------------------------------------------

class ModelRouter:
    """Routes AI tasks to the appropriate provider and model."""

    # Task type constants
    TASK_BRIEF = "brief"
    TASK_STANCE = "stance_classification"
    TASK_TRANSLATE = "translation"
    TASK_EMBED = "embedding"
    TASK_SUMMARISE = "summarisation"
    TASK_ENRICH = "entity_enrichment"
    TASK_IMAGE = "image_analysis"
    TASK_NARRATIVE_TITLE = "narrative_title"
    TASK_NARRATIVE_LABEL = "narrative_label"
    TASK_NARRATIVE_CONFIRMATION = "narrative_confirmation"
    TASK_TRACKED_NARRATIVE_MATCH = "tracked_narrative_match"
    TASK_ENTITY_RESOLUTION_ASSIST = "entity_resolution_assist"

    # Default task-to-model mapping
    DEFAULT_TASK_MODELS: dict[str, str] = {
        TASK_BRIEF: "grok-3-mini",
        TASK_STANCE: "grok-3-mini",
        TASK_TRANSLATE: "grok-3-mini",
        TASK_EMBED: "hash",  # hash-based fallback, no API needed
        TASK_SUMMARISE: "grok-3-mini",
        TASK_ENRICH: "grok-3-mini",
        TASK_IMAGE: "openai/gpt-4o",
        TASK_NARRATIVE_TITLE: "grok-3-mini",
        TASK_NARRATIVE_LABEL: "grok-3-mini",
        TASK_NARRATIVE_CONFIRMATION: "grok-3-mini",
        TASK_TRACKED_NARRATIVE_MATCH: "grok-3-mini",
        TASK_ENTITY_RESOLUTION_ASSIST: "grok-3-mini",
    }

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._task_overrides: dict[str, str] = {}   # task -> model_id
        self._model_to_provider: dict[str, str] = {}  # model_id -> provider_name

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_provider(self, name: str, provider: LLMProvider) -> None:
        """Register a provider (e.g., 'openrouter', 'ollama', 'xai', 'local')."""
        self._providers[name] = provider
        logger.info("Registered LLM provider: %s (%s)", name, type(provider).__name__)

    def map_model_to_provider(self, model_id: str, provider_name: str) -> None:
        """Explicitly map a model ID to a provider name."""
        self._model_to_provider[model_id] = provider_name

    # ------------------------------------------------------------------
    # Task routing config
    # ------------------------------------------------------------------

    def set_task_model(self, task: str, model_id: str) -> None:
        """Override which model handles a specific task."""
        self._task_overrides[task] = model_id
        logger.info("Task '%s' mapped to model '%s'", task, model_id)

    def get_task_model(self, task: str) -> str:
        """Get the model assigned to a task."""
        return self._task_overrides.get(task, self.DEFAULT_TASK_MODELS.get(task, "grok-3-mini"))

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    def get_provider_for_model(self, model_id: str) -> LLMProvider | None:
        """Find which provider serves a given model.

        Resolution order:
        1. Explicit model→provider mapping set via map_model_to_provider()
        2. Provider name inferred from model_id prefix (e.g. "openai/..." → openrouter)
        3. xai provider for grok-* models
        4. First available provider as fallback
        """
        if model_id in self._model_to_provider:
            pname = self._model_to_provider[model_id]
            return self._providers.get(pname)

        # Infer from model id patterns
        if "/" in model_id:
            # OpenRouter-style namespaced model
            if "openrouter" in self._providers:
                return self._providers["openrouter"]

        if model_id.startswith("grok"):
            if "xai" in self._providers:
                return self._providers["xai"]

        # Fallback: return first registered provider
        if self._providers:
            return next(iter(self._providers.values()))

        return None

    def _provider_name_for_model(self, model_id: str) -> str:
        """Return a human-readable provider name for logging."""
        if model_id in self._model_to_provider:
            return self._model_to_provider[model_id]
        if "/" in model_id and "openrouter" in self._providers:
            return "openrouter"
        if model_id.startswith("grok") and "xai" in self._providers:
            return "xai"
        if self._providers:
            return next(iter(self._providers))
        return "none"

    # ------------------------------------------------------------------
    # Core routing methods
    # ------------------------------------------------------------------

    async def chat(self, task: str, messages: list[dict], **kwargs) -> dict:
        """Route a chat request to the correct provider based on task config.

        Accepts an optional ``model`` kwarg to bypass task routing.

        Returns:
            {"content": str, "usage": dict, "model": str, "provider": str}
        """
        model_id: str = kwargs.pop("model", None) or self.get_task_model(task)
        provider = self.get_provider_for_model(model_id)
        provider_name = self._provider_name_for_model(model_id)

        if provider is None:
            raise RuntimeError(
                f"No provider available for model '{model_id}' (task: {task}). "
                "Register at least one provider via model_router.register_provider()."
            )

        t0 = time.monotonic()
        try:
            result = await provider.chat(messages, model_id, **kwargs)
            latency_ms = int((time.monotonic() - t0) * 1000)
            usage = result.get("usage", {})
            logger.info(
                "LLM chat | provider=%s model=%s task=%s latency_ms=%d "
                "tokens_in=%d tokens_out=%d",
                provider_name,
                model_id,
                task,
                latency_ms,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
            result["provider"] = provider_name
            return result
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.warning(
                "LLM chat error | provider=%s model=%s task=%s latency_ms=%d error=%s",
                provider_name, model_id, task, latency_ms, exc,
            )
            # Try fallback: iterate over other providers
            for fallback_name, fallback_provider in self._providers.items():
                if fallback_name == provider_name:
                    continue
                try:
                    t1 = time.monotonic()
                    result = await fallback_provider.chat(messages, model_id, **kwargs)
                    latency_ms = int((time.monotonic() - t1) * 1000)
                    usage = result.get("usage", {})
                    logger.info(
                        "LLM chat (fallback) | provider=%s model=%s task=%s latency_ms=%d",
                        fallback_name, model_id, task, latency_ms,
                    )
                    result["provider"] = fallback_name
                    return result
                except Exception as fb_exc:
                    logger.warning("Fallback provider %s also failed: %s", fallback_name, fb_exc)
            raise RuntimeError(f"All providers failed for task '{task}': {exc}") from exc

    async def embed(self, text: str, task: str = TASK_EMBED) -> list[float]:
        """Route an embedding request."""
        model_id = self.get_task_model(task)
        provider = self.get_provider_for_model(model_id)
        provider_name = self._provider_name_for_model(model_id)

        if provider is None:
            logger.warning("No embed provider available — returning empty vector")
            return []

        t0 = time.monotonic()
        try:
            result = await provider.embed(text, model_id)
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "LLM embed | provider=%s model=%s task=%s latency_ms=%d dims=%d",
                provider_name, model_id, task, latency_ms, len(result),
            )
            return result
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.warning(
                "LLM embed error | provider=%s model=%s task=%s latency_ms=%d error=%s",
                provider_name, model_id, task, latency_ms, exc,
            )
            # Try fallback providers
            for fallback_name, fallback_provider in self._providers.items():
                if fallback_name == provider_name:
                    continue
                try:
                    result = await fallback_provider.embed(text, model_id)
                    logger.info("LLM embed (fallback) | provider=%s", fallback_name)
                    return result
                except Exception as fb_exc:
                    logger.warning("Embed fallback provider %s failed: %s", fallback_name, fb_exc)
            return []

    async def list_all_models(self) -> list[dict]:
        """List all available models across all registered providers."""
        models: list[dict] = []
        for name, provider in self._providers.items():
            try:
                provider_models = await provider.list_models()
                for m in provider_models:
                    m.setdefault("provider", name)
                models.extend(provider_models)
            except Exception as exc:
                logger.warning("list_models failed for provider %s: %s", name, exc)
        return models


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

model_router = ModelRouter()
