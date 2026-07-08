"""Pydantic AI model/agent factory for OpenRouter (cloud) and Ollama (local).

Phase 1 wrapper: mirrors ``llm.call_llm`` model resolution and reuses the shared
``httpx.AsyncClient`` from ``llm`` when registered. Graph nodes and tools wire in later phases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import httpx
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.config import settings
from app.services import llm as llm_http

ModelSource = Literal["cloud", "local"]

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class ResolvedPaModel:
    """Resolved LLM backend and model id (aligned with ``call_llm``)."""

    source: ModelSource
    model: str


def resolve_pa_model(
    model_source: str,
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
) -> ResolvedPaModel:
    """Resolve ``model_source`` + optional overrides to cloud/local model id."""
    src = (model_source or "cloud").lower()
    if src == "local":
        return ResolvedPaModel(source="local", model=local_model_id or settings.OLLAMA_MODEL)
    if src == "cloud":
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY missing")
        return ResolvedPaModel(
            source="cloud",
            model=cloud_model_id or settings.OPENROUTER_MODEL,
        )
    raise ValueError(f"Unknown modelSource: {model_source}")


def ollama_openai_base_url(base: str | None = None) -> str:
    """Map app ``OLLAMA_BASE`` (native API root) to OpenAI-compatible ``/v1`` root."""
    root = (base or settings.OLLAMA_BASE).rstrip("/")
    if root.endswith("/v1"):
        return root
    return f"{root}/v1"


def _shared_http_client() -> httpx.AsyncClient | None:
    return llm_http.get_shared_llm_http_client()


class _SafeOpenAIChatModel(OpenAIChatModel):
    """OpenAIChatModel that fast-fails on finish_reason='error' instead of retrying."""

    def _map_finish_reason(self, key: Any) -> Any:
        if key == "error":
            raise UnexpectedModelBehavior(
                "Model returned finish_reason='error' — upstream provider error"
            )
        return super()._map_finish_reason(key)


def build_openrouter_chat_model(
    model: str,
    *,
    api_key: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    app_title: str | None = None,
) -> OpenAIChatModel:
    """OpenRouter-backed ``OpenAIChatModel`` (OpenAI-compatible chat completions)."""
    key = api_key if api_key is not None else settings.OPENROUTER_API_KEY
    if not key:
        raise ValueError("OPENROUTER_API_KEY missing")
    client = http_client if http_client is not None else _shared_http_client()
    provider = OpenRouterProvider(
        api_key=key,
        app_title=app_title or settings.APP_TITLE,
        http_client=client,
    )
    return _SafeOpenAIChatModel(model, provider=provider)


def build_ollama_chat_model(
    model: str,
    *,
    base_url: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> OpenAIChatModel:
    """Ollama-backed ``OpenAIChatModel`` via OpenAI-compatible ``/v1`` API."""
    client = http_client if http_client is not None else _shared_http_client()
    provider = OllamaProvider(
        base_url=ollama_openai_base_url(base_url),
        http_client=client,
    )
    return OpenAIChatModel(model, provider=provider)


def build_chat_model(
    model_source: str,
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> OpenAIChatModel:
    """Build a Pydantic AI chat model for cloud (OpenRouter) or local (Ollama)."""
    resolved = resolve_pa_model(
        model_source,
        cloud_model_id=cloud_model_id,
        local_model_id=local_model_id,
    )
    if resolved.source == "local":
        return build_ollama_chat_model(
            resolved.model,
            http_client=http_client,
        )
    return build_openrouter_chat_model(
        resolved.model,
        http_client=http_client,
    )


def create_pa_agent(
    model_source: str,
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    instructions: str | None = None,
    result_type: type[ResultT] | None = None,
    **agent_kwargs: Any,
) -> Agent[None, ResultT] | Agent[None, str]:
    """Create a Pydantic AI ``Agent`` wired to OpenRouter or Ollama."""
    model = build_chat_model(
        model_source,
        cloud_model_id=cloud_model_id,
        local_model_id=local_model_id,
        http_client=http_client,
    )
    if result_type is not None:
        return Agent(model, instructions=instructions, output_type=result_type, **agent_kwargs)
    return Agent(model, instructions=instructions, **agent_kwargs)
