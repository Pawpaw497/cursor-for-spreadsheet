"""LLM debug NDJSON logging (optional local disk)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.logging_config import reset_trace_id, set_trace_id
from app.services import llm as llm_mod
from app.services import llm_debug_log as debug_mod
from app.services.prompts import Message


def test_append_record_disabled_when_dir_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(debug_mod.settings, "LLM_DEBUG_LOG_DIR", "")
    debug_mod.append_record("tid", {"hello": 1})
    assert list(tmp_path.iterdir()) == []


def test_append_record_writes_jsonl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "llm-debug"
    monkeypatch.setattr(debug_mod.settings, "LLM_DEBUG_LOG_DIR", str(log_dir))
    token = set_trace_id("trace-abc-123")
    try:
        debug_mod.append_record(None, {"call": "plain", "model": "m"})
    finally:
        reset_trace_id(token)

    day_dirs = list(log_dir.iterdir())
    assert len(day_dirs) == 1
    files = list(day_dirs[0].glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].name == "trace-abc-123.jsonl"
    line = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert line["call"] == "plain"
    assert line["model"] == "m"


def test_prepare_messages_truncates_long_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(debug_mod.settings, "LLM_DEBUG_MAX_CHARS", 10)
    msgs = debug_mod.prepare_messages_for_log(
        [{"role": "user", "content": "x" * 100}]
    )
    assert msgs[0]["truncated"] is True
    assert len(msgs[0]["content"]) <= 11


def test_call_llm_writes_debug_log_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "llm-debug"
    monkeypatch.setattr(debug_mod.settings, "LLM_DEBUG_LOG_DIR", str(log_dir))
    monkeypatch.setattr(llm_mod.settings, "LLM_DEBUG_LOG_DIR", str(log_dir))
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_MODEL", "test/model")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": '{"steps":[]}'}}],
    }

    client_inst = MagicMock()
    client_inst.post = AsyncMock(return_value=fake_resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    token = set_trace_id("e2e-trace-xyz")
    try:

        async def run() -> str:
            with patch.object(llm_mod.httpx, "AsyncClient", return_value=cm):
                return await llm_mod.call_llm(
                    "cloud",
                    [Message.system("sys"), Message.user("hi")],
                )

        out = asyncio.run(run())
    finally:
        reset_trace_id(token)

    assert '{"steps":[]}' in out
    files = list(log_dir.rglob("e2e-trace-xyz.jsonl"))
    assert len(files) == 1
    records = [
        json.loads(ln)
        for ln in files[0].read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    assert rec["trace_id"] == "e2e-trace-xyz"
    assert rec["call"] == "plain"
    assert rec["model_source"] == "cloud"
    assert rec["result"]["content"] == '{"steps":[]}'


def test_call_llm_writes_debug_log_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "llm-debug"
    monkeypatch.setattr(debug_mod.settings, "LLM_DEBUG_LOG_DIR", str(log_dir))
    monkeypatch.setattr(llm_mod.settings, "LLM_DEBUG_LOG_DIR", str(log_dir))
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "k")

    fake_resp = MagicMock()
    fake_resp.status_code = 502
    fake_resp.text = "bad gateway"

    client_inst = MagicMock()
    client_inst.post = AsyncMock(return_value=fake_resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_inst)
    cm.__aexit__ = AsyncMock(return_value=None)

    token = set_trace_id("err-trace")
    try:

        async def run() -> None:
            with patch.object(llm_mod.httpx, "AsyncClient", return_value=cm):
                with pytest.raises(RuntimeError):
                    await llm_mod.call_llm("cloud", [Message.user("hi")])

        asyncio.run(run())
    finally:
        reset_trace_id(token)

    files = list(log_dir.rglob("err-trace.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert rec["error"]["type"] == "RuntimeError"
    assert "error" in rec
