"""OpenRouter 响应解析：畸形 JSON 结构应抛出 RuntimeError（含 [502]），避免 KeyError / IndexError 变 500。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import llm as llm_mod
from app.services.prompts import Message


@pytest.fixture(autouse=True)
def _no_shared_llm_http_client() -> None:
    """单测 mock 临时 AsyncClient 时禁用 lifespan 共享 client。"""
    llm_mod.set_shared_llm_http_client(None)
    yield  # type: ignore[misc]
    llm_mod.set_shared_llm_http_client(None)


def _mock_client(fake_resp: MagicMock) -> MagicMock:
    client_inst = MagicMock()
    client_inst.post = AsyncMock(return_value=fake_resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": None},
    ],
)
def test_call_openrouter_rejects_empty_choices(
    monkeypatch: pytest.MonkeyPatch,
    body: dict,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_MODEL", "m")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = body

    async def run() -> None:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=_mock_client(fake_resp)):
            with pytest.raises(RuntimeError, match=r"\[502\].*choices"):
                await llm_mod.call_openrouter(
                    "k",
                    "m",
                    [Message.user("hi")],
                )

    asyncio.run(run())


def test_call_openrouter_rejects_missing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_MODEL", "m")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": [{"message": {}}]}

    async def run() -> None:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=_mock_client(fake_resp)):
            with pytest.raises(RuntimeError, match=r"\[502\].*assistant content"):
                await llm_mod.call_openrouter(
                    "k",
                    "m",
                    [Message.user("hi")],
                )

    asyncio.run(run())


def test_call_openrouter_with_tools_rejects_empty_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_MODEL", "m")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": []}

    async def run() -> None:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=_mock_client(fake_resp)):
            with pytest.raises(RuntimeError, match=r"\[502\].*choices"):
                await llm_mod.call_openrouter_with_tools(
                    "k",
                    "m",
                    [{"role": "user", "content": "x"}],
                    tools=[],
                )

    asyncio.run(run())


def test_config_includes_llm_timeout_fields() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert "llmUpstreamMaxTimeoutSeconds" in data
    assert "llmClientTimeoutRecommendedMs" in data
    assert isinstance(data["llmUpstreamMaxTimeoutSeconds"], int)
    assert isinstance(data["llmClientTimeoutRecommendedMs"], int)
    assert data["llmClientTimeoutRecommendedMs"] >= data["llmUpstreamMaxTimeoutSeconds"] * 1000


def test_call_openrouter_retries_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_MODEL", "m")

    resp429 = MagicMock()
    resp429.status_code = 429
    resp429.headers = httpx.Headers({"retry-after": "0"})

    resp200 = MagicMock()
    resp200.status_code = 200
    resp200.json.return_value = {
        "choices": [{"message": {"content": "hello"}}],
    }

    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)

    client_inst = MagicMock()
    client_inst.post = AsyncMock(side_effect=[resp429, resp200])
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    async def run() -> str:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=cm):
            return await llm_mod.call_openrouter(
                "k",
                "m",
                [Message.user("hi")],
            )

    out = asyncio.run(run())
    assert out == "hello"
    assert client_inst.post.await_count == 2
    assert sleeps and sleeps[0] == 0.0


def test_call_openrouter_chat_dict_retries_empty_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")

    resp_empty = MagicMock()
    resp_empty.status_code = 200
    resp_empty.json.return_value = {
        "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
    }

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {
        "choices": [{"message": {"content": '{"intent":"x","steps":[]}'}}],
    }

    client_inst = MagicMock()
    client_inst.post = AsyncMock(side_effect=[resp_empty, resp_ok])
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    async def run() -> str:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=cm):
            return await llm_mod.call_openrouter_chat_dict(
                "k",
                "m",
                [{"role": "user", "content": "hi"}],
            )

    out = asyncio.run(run())
    assert "intent" in out
    assert client_inst.post.await_count == 2
    retry_body = client_inst.post.call_args_list[1].kwargs["json"]
    assert retry_body["messages"][-1]["role"] == "user"
    assert "non-empty" in retry_body["messages"][-1]["content"].lower()


def test_call_openrouter_chat_dict_raises_after_two_empty_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")

    resp_empty = MagicMock()
    resp_empty.status_code = 200
    resp_empty.json.return_value = {
        "choices": [{"message": {"content": "  "}, "finish_reason": "stop"}],
    }

    client_inst = MagicMock()
    client_inst.post = AsyncMock(return_value=resp_empty)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    async def run() -> None:
        with patch.object(llm_mod.httpx, "AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match=r"\[502\].*empty assistant content"):
                await llm_mod.call_openrouter_chat_dict(
                    "k",
                    "m",
                    [{"role": "user", "content": "hi"}],
                )

    asyncio.run(run())
    assert client_inst.post.await_count == 2
