"""Unified LLM model router — routes AI tasks to configured providers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger("orthanc.model_router")

# ---------------------------------------------------------------------------
# Base provider interface
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Base class for LLM providers."""

    # Capability flags — subclasses override as needed
    supports_chat: bool = True
    supports_embeddings: bool = True
    supports_vision: bool = False
    supports_response_format: bool = True   # whether provider accepts response_format kwarg

    @abstractmethod
    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        """Send chat completion request.

        Returns:
            {"content": str, "thinking": str|None, "usage": {...}, "model": str}
        """

    @abstractmethod
    async def embed(self, text: str, model: str) -> list[float]:
        """Get embedding vector."""

    async def list_models(self) -> list[dict]:
        """List available models. Returns [{"id": str, "name": str}]"""
        return []


# ---------------------------------------------------------------------------
# Helper — inject JSON instruction for providers that don't support response_format
# ---------------------------------------------------------------------------

def _inject_json_instruction(messages: list[dict]) -> list[dict]:
    """Append 'Respond in valid JSON format.' to the system message."""
    messages = list(messages)
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            messages[i] = {**msg, "content": msg["content"].rstrip() + "\nRespond in valid JSON format."}
            return messages
    # No system message — prepend one
    return [{"role": "system", "content": "Respond in valid JSON format."}] + messages


# ---------------------------------------------------------------------------
# OpenRouter provider
# ---------------------------------------------------------------------------

class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider."""

    supports_chat: bool = True
    supports_embeddings: bool = True
    supports_vision: bool = True
    supports_response_format: bool = True

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

        msg = data["choices"][0]["message"]
        content_raw = msg.get("content", "")
        thinking_content: str | None = None

        # Handle extended thinking (Claude) — content may be a list of blocks
        if isinstance(content_raw, list):
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            for block in content_raw:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "thinking":
                        thinking_parts.append(block.get("thinking", ""))
                    elif btype == "text":
                        text_parts.append(block.get("text", ""))
            content = " ".join(text_parts)
            thinking_content = "\n".join(thinking_parts) if thinking_parts else None
        else:
            content = content_raw or ""
            # Gemini / other models may return reasoning_content separately
            thinking_content = msg.get("reasoning_content") or data.get("reasoning_content") or None

        usage = data.get("usage", {})
        return {
            "content": content,
            "thinking": thinking_content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            "model": model,
        }

    async def chat_stream(self, messages: list[dict], model: str, **kwargs) -> AsyncIterator[str]:
        """Stream chat completion via SSE. Yields text chunks as they arrive."""
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True, **kwargs}
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content") or ""
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

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
    """xAI/Grok API provider (OpenAI-compatible).

    Note: xAI does NOT provide an /embeddings endpoint — supports_embeddings is False.
    """

    supports_chat: bool = True
    supports_embeddings: bool = False
    supports_vision: bool = True
    supports_response_format: bool = True

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

        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or ""
        thinking_content: str | None = msg.get("reasoning_content") or data.get("reasoning_content") or None
        usage = data.get("usage", {})
        return {
            "content": content,
            "thinking": thinking_content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
            "model": model,
        }

    async def embed(self, text: str, model: str = "v1") -> list[float]:
        raise NotImplementedError(
            "xAI/Grok does not support embeddings (/v1/embeddings is not available). "
            "Use OpenRouter or Ollama for embedding tasks."
        )

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
    """Ollama local/remote provider.

    Supports vision models (llava, bakllava, llama3.2-vision, moondream, etc.).
    OpenAI-style ``image_url`` content parts are automatically converted to
    Ollama's ``images`` list format before sending.

    Note: does NOT support response_format — uses system message injection instead.
    """

    supports_chat: bool = True
    supports_embeddings: bool = True
    supports_vision: bool = True
    supports_response_format: bool = False  # use _inject_json_instruction instead

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _convert_messages_for_ollama(messages: list[dict]) -> list[dict]:
        """Convert OpenAI-format image_url content to Ollama's ``images`` list."""
        import re
        converted = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                text_parts: list[str] = []
                images: list[str] = []
                for part in content:
                    ptype = part.get("type")
                    if ptype == "text":
                        text_parts.append(part.get("text", ""))
                    elif ptype == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        m = re.match(r"data:[^;]+;base64,(.+)", url, re.DOTALL)
                        if m:
                            images.append(m.group(1))
                        else:
                            images.append(url)
                new_msg: dict = {
                    "role": msg["role"],
                    "content": " ".join(text_parts),
                }
                if images:
                    new_msg["images"] = images
                converted.append(new_msg)
            else:
                converted.append(msg)
        return converted

    async def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        ollama_messages = self._convert_messages_for_ollama(messages)
        payload = {"model": model, "messages": ollama_messages, "stream": False}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        content = data["message"]["content"]
        return {
            "content": content,
            "thinking": None,
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

    supports_chat: bool = True
    supports_embeddings: bool = True
    supports_vision: bool = True
    supports_response_format: bool = True

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

        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or ""
        thinking_content: str | None = msg.get("reasoning_content") or data.get("reasoning_content") or None
        usage = data.get("usage", {})
        return {
            "content": content,
            "thinking": thinking_content,
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
    TASK_CLAIM_EXTRACTION = "claim_extraction"

    # Default task-to-model mapping
    DEFAULT_TASK_MODELS: dict[str, str] = {
        TASK_BRIEF: "grok-3-mini",
        TASK_STANCE: "grok-3-mini",
        TASK_TRANSLATE: "google/gemini-2.5-flash",
        TASK_EMBED: "openai/text-embedding-3-small",
        TASK_SUMMARISE: "grok-3-mini",
        TASK_ENRICH: "grok-3-mini",
        TASK_IMAGE: "openai/gpt-4o",
        TASK_NARRATIVE_TITLE: "grok-3-mini",
        TASK_NARRATIVE_LABEL: "grok-3-mini",
        TASK_NARRATIVE_CONFIRMATION: "grok-3-mini",
        TASK_TRACKED_NARRATIVE_MATCH: "grok-3-mini",
        TASK_ENTITY_RESOLUTION_ASSIST: "grok-3-mini",
        TASK_CLAIM_EXTRACTION: "grok-3-mini",
    }

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._task_overrides: dict[str, str] = {}   # task -> model_id
        self._model_to_provider: dict[str, str] = {}  # model_id -> provider_name
        # TASK-63: In-memory performance counters per model
        self._perf: dict[str, dict] = {}

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
        """Find which provider serves a given model."""
        if model_id in self._model_to_provider:
            pname = self._model_to_provider[model_id]
            return self._providers.get(pname)

        if "/" in model_id:
            if "openrouter" in self._providers:
                return self._providers["openrouter"]

        if model_id.startswith("grok"):
            if "xai" in self._providers:
                return self._providers["xai"]

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
    # TASK-63: Performance tracking helpers
    # ------------------------------------------------------------------

    def _update_perf(self, model_id: str, latency_ms: int, error: bool = False) -> None:
        """Update in-memory performance counters for a model."""
        if model_id not in self._perf:
            self._perf[model_id] = {"total_calls": 0, "total_errors": 0, "total_latency_ms": 0}
        self._perf[model_id]["total_calls"] += 1
        if error:
            self._perf[model_id]["total_errors"] += 1
        self._perf[model_id]["total_latency_ms"] += latency_ms

    def get_performance_stats(self) -> dict:
        """Return in-memory performance counters for all models."""
        result = {}
        for model_id, counters in self._perf.items():
            calls = counters["total_calls"]
            avg_latency = (counters["total_latency_ms"] / calls) if calls > 0 else 0
            result[model_id] = {
                **counters,
                "avg_latency_ms": round(avg_latency, 1),
                "error_rate": round(counters["total_errors"] / calls, 4) if calls > 0 else 0,
            }
        return result

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def _estimate_cost(self, model_id: str, tokens_in: int, tokens_out: int) -> float | None:
        """Estimate USD cost based on known model pricing."""
        # Import here to avoid circular imports
        from app.services.ai_models import get_model, _live_model_cache  # type: ignore[import]

        config = get_model(model_id)
        if not config:
            config = _live_model_cache.get(model_id)
        if not config:
            return None

        cost_in = config.get("cost_per_1k_input", 0) * tokens_in / 1000
        cost_out = config.get("cost_per_1k_output", 0) * tokens_out / 1000
        return round(cost_in + cost_out, 6) if (cost_in + cost_out) > 0 else None

    # ------------------------------------------------------------------
    # Core routing methods
    # ------------------------------------------------------------------

    async def chat(
        self,
        task: str,
        messages: list[dict],
        *,
        response_format: dict | None = None,
        **kwargs,
    ) -> dict:
        """Route a chat request to the correct provider based on task config.

        Args:
            task: Task type constant (e.g. TASK_BRIEF).
            messages: OpenAI-format message list.
            response_format: Optional structured output format, e.g. {"type": "json_object"}.
                             Forwarded to providers that support it; injected as a system prompt
                             instruction for providers that don't (Ollama).
            **kwargs: Additional kwargs forwarded to provider (e.g. model=, temperature=).

        Returns:
            {"content": str, "thinking": str|None, "usage": dict, "model": str, "provider": str}
        """
        model_id: str = kwargs.pop("model", None) or self.get_task_model(task)
        provider = self.get_provider_for_model(model_id)
        provider_name = self._provider_name_for_model(model_id)

        if provider is None:
            available = list(self._providers.keys())
            raise RuntimeError(
                f"No provider found for model '{model_id}'. "
                f"Available providers: {available}. Check Settings → Models."
            )

        # TASK-61: Handle response_format by provider capability
        effective_messages = messages
        if response_format is not None:
            if getattr(provider, "supports_response_format", True):
                kwargs["response_format"] = response_format
            else:
                # Ollama and other non-supporting providers: inject instruction
                effective_messages = _inject_json_instruction(list(messages))

        t0 = time.monotonic()
        last_error: Exception | None = None
        try:
            result = await provider.chat(effective_messages, model_id, **kwargs)
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._update_perf(model_id, latency_ms, error=False)

            # TASK-64: Log thinking content for debugging; don't expose to end-users by default
            thinking = result.get("thinking")
            if thinking:
                logger.debug(
                    "LLM thinking | provider=%s model=%s task=%s thinking=%.200s…",
                    provider_name, model_id, task, thinking,
                )

            usage = result.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            logger.info(
                "LLM chat | provider=%s model=%s task=%s latency_ms=%d "
                "tokens_in=%d tokens_out=%d",
                provider_name, model_id, task, latency_ms,
                tokens_in,
                tokens_out,
            )
            try:
                from app.services.llm_usage_service import llm_usage_service  # noqa: PLC0415
                asyncio.ensure_future(llm_usage_service.log_usage(
                    provider=provider_name,
                    model=model_id,
                    task=task,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    cost_usd=self._estimate_cost(model_id, tokens_in, tokens_out),
                ))
            except Exception as _log_exc:
                logger.debug("Usage logging skipped: %s", _log_exc)
            result["provider"] = provider_name
            return result
        except Exception as exc:
            last_error = exc
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._update_perf(model_id, latency_ms, error=True)
            logger.warning(
                "LLM chat error | provider=%s model=%s task=%s latency_ms=%d error=%s",
                provider_name, model_id, task, latency_ms, exc,
            )
            # Try fallback providers
            for fallback_name, fallback_provider in self._providers.items():
                if fallback_name == provider_name:
                    continue
                try:
                    t1 = time.monotonic()
                    result = await fallback_provider.chat(effective_messages, model_id, **kwargs)
                    latency_ms = int((time.monotonic() - t1) * 1000)
                    self._update_perf(model_id, latency_ms, error=False)
                    usage = result.get("usage", {})
                    fb_tokens_in = usage.get("prompt_tokens", 0)
                    fb_tokens_out = usage.get("completion_tokens", 0)
                    logger.info(
                        "LLM chat (fallback) | provider=%s model=%s task=%s latency_ms=%d",
                        fallback_name, model_id, task, latency_ms,
                    )
                    try:
                        from app.services.llm_usage_service import llm_usage_service  # noqa: PLC0415
                        asyncio.ensure_future(llm_usage_service.log_usage(
                            provider=fallback_name,
                            model=model_id,
                            task=task,
                            tokens_in=fb_tokens_in,
                            tokens_out=fb_tokens_out,
                            latency_ms=latency_ms,
                            cost_usd=self._estimate_cost(model_id, fb_tokens_in, fb_tokens_out),
                        ))
                    except Exception as _log_exc:
                        logger.debug("Usage logging skipped (fallback): %s", _log_exc)
                    result["provider"] = fallback_name
                    return result
                except Exception as fb_exc:
                    last_error = fb_exc
                    logger.warning("Fallback provider %s also failed: %s", fallback_name, fb_exc)
            raise RuntimeError(
                f"All providers failed for task '{task}'. "
                f"Last error: {last_error}. Check API keys and provider health."
            ) from last_error

    async def chat_stream(
        self,
        task: str,
        messages: list[dict],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream a chat response. Currently implemented for OpenRouter; others yield full response.

        This is a foundation method — not yet wired into any endpoint.
        Yields text chunks as they arrive from the model.
        """
        model_id: str = kwargs.pop("model", None) or self.get_task_model(task)
        provider = self.get_provider_for_model(model_id)

        if provider is None:
            available = list(self._providers.keys())
            raise RuntimeError(
                f"No provider found for model '{model_id}'. "
                f"Available providers: {available}. Check Settings → Models."
            )

        if isinstance(provider, OpenRouterProvider):
            async for chunk in provider.chat_stream(messages, model_id, **kwargs):
                yield chunk
        else:
            # Non-streaming fallback: call regular chat and yield the full content
            result = await provider.chat(messages, model_id, **kwargs)
            yield result.get("content", "")

    def _get_embed_capable_provider(self, model_id: str) -> tuple[LLMProvider | None, str]:
        """Resolve an embedding-capable provider for the given model_id."""
        candidate = self.get_provider_for_model(model_id)
        candidate_name = self._provider_name_for_model(model_id)
        if candidate is not None and getattr(candidate, "supports_embeddings", True):
            return candidate, candidate_name

        if candidate is not None:
            logger.warning(
                "Provider '%s' does not support embeddings (model=%s). "
                "Searching for an embedding-capable provider.",
                candidate_name, model_id,
            )

        priority_order = ["openrouter", "ollama", "local"]
        for pname in priority_order:
            p = self._providers.get(pname)
            if p is not None and getattr(p, "supports_embeddings", True):
                return p, pname

        for pname, p in self._providers.items():
            if getattr(p, "supports_embeddings", True):
                return p, pname

        return None, "none"

    async def embed(self, text: str, task: str = TASK_EMBED) -> list[float]:
        """Route an embedding request, skipping providers that don't support embeddings."""
        model_id = self.get_task_model(task)
        provider, provider_name = self._get_embed_capable_provider(model_id)

        if provider is None:
            logger.warning(
                "No embedding provider available (model=%s task=%s) — returning empty vector. "
                "Set an embedding model in Settings → Models → Task Assignments.",
                model_id, task,
            )
            return []

        t0 = time.monotonic()
        try:
            result = await provider.embed(text, model_id)
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._update_perf(model_id, latency_ms, error=False)
            logger.info(
                "LLM embed | provider=%s model=%s task=%s latency_ms=%d dims=%d",
                provider_name, model_id, task, latency_ms, len(result),
            )
            try:
                from app.services.llm_usage_service import llm_usage_service  # noqa: PLC0415
                # Approximate tokens_in from text length; embed has no output tokens
                approx_tokens = max(1, len(text) // 4)
                asyncio.ensure_future(llm_usage_service.log_usage(
                    provider=provider_name,
                    model=model_id,
                    task=task,
                    tokens_in=approx_tokens,
                    tokens_out=0,
                    latency_ms=latency_ms,
                    cost_usd=self._estimate_cost(model_id, approx_tokens, 0),
                ))
            except Exception as _log_exc:
                logger.debug("Usage logging skipped (embed): %s", _log_exc)
            return result
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._update_perf(model_id, latency_ms, error=True)
            logger.warning(
                "LLM embed error | provider=%s model=%s task=%s latency_ms=%d error=%s",
                provider_name, model_id, task, latency_ms, exc,
            )
            for fallback_name, fallback_provider in self._providers.items():
                if fallback_name == provider_name:
                    continue
                if not getattr(fallback_provider, "supports_embeddings", True):
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
