"""Shared LLM httpx.AsyncClient lifecycle, injection, and concurrent use."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.main import lifespan, app
from app.services import llm as llm_mod


@pytest.fixture(autouse=True)
def _reset_shared_llm_client() -> None:
    llm_mod.set_shared_llm_http_client(None)
    yield  # type: ignore[misc]
    llm_mod.set_shared_llm_http_client(None)


def test_create_llm_http_client_returns_open_client() -> None:
    client = llm_mod.create_llm_http_client()
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed
    finally:
        asyncio.run(client.aclose())


def test_lifespan_registers_and_closes_shared_client() -> None:
    async def run() -> None:
        assert llm_mod.get_shared_llm_http_client() is None
        async with lifespan(app):
            shared = llm_mod.get_shared_llm_http_client()
            assert shared is not None
            assert not shared.is_closed
        assert llm_mod.get_shared_llm_http_client() is None

    asyncio.run(run())


def test_post_with_retries_uses_injected_client() -> None:
    seen_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    async def run() -> httpx.Response:
        try:
            return await llm_mod._post_with_retries(
                client,
                "http://mock.test/post",
                headers={"X-Test": "1"},
                json_body={"a": 1},
                timeout=5.0,
                upstream="Mock",
            )
        finally:
            await client.aclose()

    resp = asyncio.run(run())
    assert resp.status_code == 200
    assert seen_urls == ["http://mock.test/post"]


def test_httpx_post_json_ephemeral_without_shared_client() -> None:
    created: list[bool] = []

    fake_resp = MagicMock()
    fake_resp.status_code = 200

    client_inst = MagicMock()
    client_inst.post = AsyncMock(return_value=fake_resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    def track_client(*_args, **_kwargs):
        created.append(True)
        return cm

    async def run() -> None:
        with patch.object(llm_mod.httpx, "AsyncClient", side_effect=track_client):
            llm_mod.set_shared_llm_http_client(None)
            resp = await llm_mod._httpx_post_json(
                "http://mock.test/",
                headers=None,
                json_body={},
                timeout=1.0,
                upstream="Mock",
            )
            assert resp.status_code == 200

    asyncio.run(run())
    assert created == [True]
    client_inst.post.assert_awaited_once()


def test_concurrent_shared_client_requests_no_closed_error() -> None:
    call_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.005)
        return httpx.Response(200, json={"n": call_count})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, limits=llm_mod.LLM_HTTP_LIMITS)
    llm_mod.set_shared_llm_http_client(client)

    async def run() -> list[httpx.Response]:
        try:
            return await asyncio.gather(
                *[
                    llm_mod._httpx_post_json(
                        "http://mock.test/",
                        headers=None,
                        json_body={"i": i},
                        timeout=5.0,
                        upstream="Mock",
                    )
                    for i in range(30)
                ]
            )
        finally:
            llm_mod.set_shared_llm_http_client(None)
            await client.aclose()

    results = asyncio.run(run())
    assert len(results) == 30
    assert all(r.status_code == 200 for r in results)
    assert call_count == 30


def test_shared_client_cleared_after_aclose_prevents_reuse() -> None:
    async def run() -> None:
        client = llm_mod.create_llm_http_client()
        llm_mod.set_shared_llm_http_client(client)
        await client.aclose()
        llm_mod.set_shared_llm_http_client(None)
        assert llm_mod.get_shared_llm_http_client() is None

        with pytest.raises(RuntimeError, match="closed"):
            await client.post("http://example.com/")

    asyncio.run(run())
