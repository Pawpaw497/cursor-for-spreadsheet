"""LLM 调用：Ollama / OpenRouter。"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, TypeAlias, overload

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.services.llm_debug_log import (
    build_error_payload,
    build_result_payload,
    log_llm_call,
)
from app.services.prompts import Message

log = get_logger("services.llm")

# 对 429 / 503 与连接类 transient 错误的有限次重试（在同一 injectable AsyncClient 上循环 post）。
MAX_LLM_HTTP_ATTEMPTS: int = 3
_LLM_RETRY_BACKOFF_BASE_S: float = 0.35
_LLM_RETRY_BACKOFF_CAP_S: float = 30.0

# 进程级共享 LLM HTTP 连接池上限（由 FastAPI lifespan 创建 client 时使用）。
LLM_HTTP_LIMITS = httpx.Limits(
    max_connections=50,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)

# httpx 客户端超时（秒）。与前端 `TIMEOUT_LLM_MS` 对齐时以 `max_llm_upstream_http_timeout_seconds()` 为基准加缓冲。
OPENROUTER_HTTP_TIMEOUT_CHAT_S: float = 60.0
OPENROUTER_HTTP_TIMEOUT_TOOLS_S: float = 90.0
OLLAMA_HTTP_TIMEOUT_S: float = 120.0

_shared_llm_http_client: httpx.AsyncClient | None = None


def create_llm_http_client() -> httpx.AsyncClient:
    """创建带连接池上限的 LLM 专用 AsyncClient（lifespan 与单测注入）。"""
    return httpx.AsyncClient(limits=LLM_HTTP_LIMITS)


def get_shared_llm_http_client() -> httpx.AsyncClient | None:
    """返回 lifespan 注册的共享 client；未注册时为 ``None``（走临时 client 路径）。"""
    return _shared_llm_http_client


def set_shared_llm_http_client(client: httpx.AsyncClient | None) -> None:
    """注册或清除共享 client（关闭后应设为 ``None``，避免复用已 closed 实例）。"""
    global _shared_llm_http_client
    _shared_llm_http_client = client


def max_llm_upstream_http_timeout_seconds() -> int:
    """当前实现中各上游 LLM HTTP 调用的最大秒数（供 /api/config 与前端缓冲对齐）。"""
    return int(
        max(
            OPENROUTER_HTTP_TIMEOUT_CHAT_S,
            OPENROUTER_HTTP_TIMEOUT_TOOLS_S,
            OLLAMA_HTTP_TIMEOUT_S,
        )
    )


def recommended_llm_client_timeout_ms(*, buffer_seconds: float = 30.0) -> int:
    """建议的前端 LLM 请求总超时（毫秒）= 后端最大 HTTP 超时 + 缓冲。"""
    return int((max_llm_upstream_http_timeout_seconds() + buffer_seconds) * 1000)


def _retry_after_delay_seconds(resp: httpx.Response) -> float | None:
    """解析 ``Retry-After``（仅支持秒数整数）；无法解析时返回 ``None`` 由调用方用指数退避。"""
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(int(raw)))
    except ValueError:
        return None


def _read_response_json(resp: httpx.Response, *, upstream: str) -> Any:
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"[502] {upstream} returned malformed JSON (HTTP {resp.status_code})."
        ) from e


async def _post_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None,
    json_body: Any,
    timeout: float,
    upstream: str,
) -> httpx.Response:
    """在已打开的 ``client`` 上 POST JSON；对 429/503 与 ``RequestError`` 做有限次重试。"""
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = await client.post(
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
        except httpx.TimeoutException as e:
            raise RuntimeError(
                f"[502] {upstream} request timed out after {timeout:g}s."
            ) from e
        except httpx.RequestError as e:
            if attempt >= MAX_LLM_HTTP_ATTEMPTS:
                raise RuntimeError(
                    f"[502] {upstream} request failed ({type(e).__name__})."
                ) from e
            delay = min(
                _LLM_RETRY_BACKOFF_CAP_S,
                _LLM_RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1)),
            )
            log.warning(
                "llm_http_retry upstream=%s attempt=%d/%d err=%s sleep_s=%.2f",
                upstream,
                attempt,
                MAX_LLM_HTTP_ATTEMPTS,
                type(e).__name__,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        if resp.status_code in (429, 503) and attempt < MAX_LLM_HTTP_ATTEMPTS:
            ra = _retry_after_delay_seconds(resp)
            if ra is None:
                ra = min(
                    _LLM_RETRY_BACKOFF_CAP_S,
                    _LLM_RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1)),
                )
            delay = min(_LLM_RETRY_BACKOFF_CAP_S, max(0.0, ra))
            log.warning(
                "llm_http_retry upstream=%s attempt=%d/%d status=%d sleep_s=%.2f",
                upstream,
                attempt,
                MAX_LLM_HTTP_ATTEMPTS,
                resp.status_code,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        return resp


async def _httpx_post_json(
    url: str,
    *,
    headers: dict[str, str] | None,
    json_body: Any,
    timeout: float,
    upstream: str,
) -> httpx.Response:
    """POST JSON；生产路径复用 lifespan 共享 client，单测无注入时使用临时 client。"""
    shared = get_shared_llm_http_client()
    if shared is not None:
        return await _post_with_retries(
            shared,
            url,
            headers=headers,
            json_body=json_body,
            timeout=timeout,
            upstream=upstream,
        )
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await _post_with_retries(
            client,
            url,
            headers=headers,
            json_body=json_body,
            timeout=timeout,
            upstream=upstream,
        )

# call_llm 普通 chat 可用的消息形态：结构化 Message 或与 tools 对齐的 OpenAI-compatible dict。
LLMPlainMessages: TypeAlias = list[Message] | list[dict[str, Any]]

# 带 tools 时返回：(content 或 None, tool_calls 或 None)
# tool_calls: list[dict] 每项 {"id": str, "name": str, "arguments": str}
LLMWithToolsResult = tuple[str | None, list[dict] | None]


def _message_stats(messages: list[Message]) -> tuple[int, int]:
    """返回消息条数与内容字符总数（用于日志，不落库全文）。"""
    n = len(messages)
    total = sum(len(m.content or "") for m in messages)
    return n, total


def _dict_message_stats(messages: list[dict]) -> tuple[int, int]:
    """dict 形态 messages 的条数与内容字符估计。"""
    n = len(messages)
    total = sum(len(str(m.get("content") or "")) for m in messages)
    return n, total


def _messages_to_payload(messages: list[Message]) -> list[dict]:
    return [m.to_dict() for m in messages]


def _messages_with_tools_to_payload(messages: list[dict]) -> list[dict]:
    """将支持 tool_calls / tool 的 message 列表转为 API 所需格式。"""
    out: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        msg: dict[str, Any] = {"role": role}
        if role == "tool":
            msg["content"] = m.get("content", "")
            if m.get("tool_call_id"):
                msg["tool_call_id"] = m["tool_call_id"]
        else:
            if m.get("content") is not None:
                msg["content"] = m["content"]
            if m.get("tool_calls"):
                msg["tool_calls"] = m["tool_calls"]
        out.append(msg)
    return out


def _raise_openrouter_error(resp: httpx.Response) -> None:
    """解析 OpenRouter 错误响应并抛出结构化 RuntimeError。

    对 401/403 等鉴权错误增加 AUTH_ERROR 前缀，便于上层路由区分并返回更友好的提示。

    Args:
        resp: OpenRouter HTTP 响应对象。

    Raises:
        RuntimeError: 总是抛出，消息中包含精简的人类可读文案和原始响应片段。
    """
    status = resp.status_code
    body_text = resp.text or "<empty body>"

    error_code: Any | None = None
    error_message: str | None = None

    try:
        data = resp.json()
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            err = data["error"]
            error_code = err.get("code")
            if isinstance(error_code, dict):
                # 极端情况下 code 也是嵌套结构，这里做一次保护性展开。
                error_code = err.get("code", {}).get("code")
            if isinstance(err.get("message"), str):
                error_message = err["message"]
    except Exception:
        data = None  # noqa: F841  # 仅用于调试时临时打印，不在这里使用

    human_detail = error_message or body_text
    base_msg = f"OpenRouter HTTP {status}: {human_detail}"

    # 针对典型鉴权错误增加前缀，后续路由可据此返回更友好的中文提示。
    is_auth_error = status in (401, 403)
    if isinstance(error_code, (int, str)) and str(error_code) in {"401", "403"}:
        is_auth_error = True

    if is_auth_error:
        raise RuntimeError(f"AUTH_ERROR: {base_msg}. Raw: {body_text}")

    raise RuntimeError(f"[502] {base_msg}. Raw: {body_text}")


def _parse_tool_calls_from_response(raw: list[dict] | None) -> list[dict] | None:
    """从 API 返回的 tool_calls 转为 [{"id", "name", "arguments"}]。"""
    if not raw:
        return None
    result = []
    for tc in raw:
        fn = tc.get("function") or {}
        result.append({
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "arguments": fn.get("arguments", "{}"),
        })
    return result if result else None


async def call_ollama(model: str, messages: list[Message]) -> str:
    base = settings.OLLAMA_BASE
    url = f"{base}/api/chat"
    payload = {
        "model": model,
        "messages": _messages_to_payload(messages),
        "stream": False,
    }
    r = await _httpx_post_json(
        url,
        headers=None,
        json_body=payload,
        timeout=OLLAMA_HTTP_TIMEOUT_S,
        upstream="Ollama",
    )
    if r.status_code >= 400:
        detail = r.text or "<empty body>"
        raise RuntimeError(f"[502] Ollama error {r.status_code}: {detail}")
    data = _read_response_json(r, upstream="Ollama")
    return data.get("message", {}).get("content", "")


async def call_ollama_chat_dict(model: str, messages: list[dict[str, Any]]) -> str:
    """Ollama 普通 chat（无 tools）；messages 可与 tool_calls / tool transcript 对齐。"""
    base = settings.OLLAMA_BASE
    url = f"{base}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages_with_tools_to_payload(messages),
        "stream": False,
    }
    r = await _httpx_post_json(
        url,
        headers=None,
        json_body=payload,
        timeout=OLLAMA_HTTP_TIMEOUT_S,
        upstream="Ollama",
    )
    if r.status_code >= 400:
        detail = r.text or "<empty body>"
        raise RuntimeError(f"[502] Ollama error {r.status_code}: {detail}")
    data = _read_response_json(r, upstream="Ollama")
    return data.get("message", {}).get("content", "")


_OPENROUTER_EMPTY_CONTENT_RETRY_USER = (
    "Return ONLY non-empty assistant content. "
    "If generating a spreadsheet plan, return ONLY valid JSON."
)


def _openrouter_choice_assistant_content(
    data: dict[str, Any],
    *,
    model: str,
    upstream_label: str,
) -> str:
    """从 chat completions JSON 解析 assistant ``content``；空或缺失则抛 ``RuntimeError``。"""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"[502] {upstream_label} response missing or empty choices.")
    choice0 = choices[0]
    if not isinstance(choice0, dict):
        raise RuntimeError(f"[502] {upstream_label} response malformed choice entry.")
    msg = choice0.get("message") or {}
    if not isinstance(msg, dict):
        raise RuntimeError(f"[502] {upstream_label} response missing assistant message.")
    content = msg.get("content")
    finish_reason = choice0.get("finish_reason")
    if content is None:
        log.warning(
            "%s missing assistant content model=%s finish_reason=%s "
            "message_keys=%s native_finish_reason=%s",
            upstream_label,
            model,
            finish_reason,
            list(msg.keys()),
            choice0.get("native_finish_reason"),
        )
        raise RuntimeError(f"[502] {upstream_label} response missing assistant content.")
    if not isinstance(content, str):
        raise RuntimeError(f"[502] {upstream_label} assistant content has unexpected type.")
    if not content.strip():
        log.warning(
            "%s empty assistant content model=%s finish_reason=%s "
            "message_keys=%s native_finish_reason=%s",
            upstream_label,
            model,
            finish_reason,
            list(msg.keys()),
            choice0.get("native_finish_reason"),
        )
        raise RuntimeError(f"[502] {upstream_label} returned empty assistant content.")
    return content


async def _openrouter_chat_dict_request(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """POST OpenRouter chat completions；返回解析后的 JSON body。"""
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "messages": _messages_with_tools_to_payload(messages),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = await _httpx_post_json(
        url,
        headers=headers,
        json_body=payload,
        timeout=OPENROUTER_HTTP_TIMEOUT_CHAT_S,
        upstream="OpenRouter",
    )
    if r.status_code >= 400:
        _raise_openrouter_error(r)
    data = _read_response_json(r, upstream="OpenRouter")
    if not isinstance(data, dict):
        raise RuntimeError("[502] OpenRouter response root is not a JSON object.")
    return data


async def call_openrouter_chat_dict(api_key: str, model: str, messages: list[dict[str, Any]]) -> str:
    """OpenRouter 普通 chat completions（无 tools / tool_choice）。

    若首轮 assistant ``content`` 为空，在 transcript 末尾追加一条 user 重试提示后再请求一次；
    仍空则抛出与 ``call_openrouter`` 对齐的 ``RuntimeError``。
    """
    data = await _openrouter_chat_dict_request(api_key, model, messages)
    try:
        return _openrouter_choice_assistant_content(
            data, model=model, upstream_label="OpenRouter"
        )
    except RuntimeError:
        retry_messages = list(messages) + [
            {"role": "user", "content": _OPENROUTER_EMPTY_CONTENT_RETRY_USER},
        ]
        log.warning(
            "openrouter_chat_dict retrying after empty content model=%s messages=%d",
            model,
            len(messages),
        )
        data_retry = await _openrouter_chat_dict_request(api_key, model, retry_messages)
        return _openrouter_choice_assistant_content(
            data_retry, model=model, upstream_label="OpenRouter"
        )


async def call_openrouter(api_key: str, model: str, messages: list[Message]) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": _messages_to_payload(messages),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = await _httpx_post_json(
        url,
        headers=headers,
        json_body=payload,
        timeout=OPENROUTER_HTTP_TIMEOUT_CHAT_S,
        upstream="OpenRouter",
    )
    if r.status_code >= 400:
        _raise_openrouter_error(r)
    data = _read_response_json(r, upstream="OpenRouter")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("[502] OpenRouter response missing or empty choices.")
    choice0 = choices[0]
    if not isinstance(choice0, dict):
        raise RuntimeError("[502] OpenRouter response malformed choice entry.")
    msg = choice0.get("message")
    if not isinstance(msg, dict):
        raise RuntimeError("[502] OpenRouter response missing assistant message.")
    content = msg.get("content")
    finish_reason = choice0.get("finish_reason")
    if content is None:
        log.warning(
            "openrouter missing assistant content model=%s finish_reason=%s "
            "message_keys=%s native_finish_reason=%s",
            model,
            finish_reason,
            list(msg.keys()),
            choice0.get("native_finish_reason"),
        )
        raise RuntimeError("[502] OpenRouter response missing assistant content.")
    if not isinstance(content, str):
        raise RuntimeError("[502] OpenRouter assistant content has unexpected type.")
    if not content.strip():
        log.warning(
            "openrouter empty assistant content model=%s finish_reason=%s "
            "message_keys=%s native_finish_reason=%s",
            model,
            finish_reason,
            list(msg.keys()),
            choice0.get("native_finish_reason"),
        )
        raise RuntimeError("[502] OpenRouter returned empty assistant content.")
    return content


async def call_openrouter_with_tools(
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
) -> LLMWithToolsResult:
    """OpenRouter 带 tools 的调用；返回 (content, tool_calls)。"""
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "messages": _messages_with_tools_to_payload(messages),
        "tools": tools,
        "tool_choice": "auto",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = await _httpx_post_json(
        url,
        headers=headers,
        json_body=payload,
        timeout=OPENROUTER_HTTP_TIMEOUT_TOOLS_S,
        upstream="OpenRouter",
    )
    if r.status_code >= 400:
        _raise_openrouter_error(r)
    data = _read_response_json(r, upstream="OpenRouter")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("[502] OpenRouter response missing or empty choices.")
    choice0 = choices[0]
    if not isinstance(choice0, dict):
        raise RuntimeError("[502] OpenRouter response malformed choice entry.")
    raw_msg = choice0.get("message")
    if raw_msg is None:
        msg = {}
    elif not isinstance(raw_msg, dict):
        raise RuntimeError("[502] OpenRouter response missing assistant message.")
    else:
        msg = raw_msg
    finish_reason = choice0.get("finish_reason")
    content = msg.get("content") or None
    if isinstance(content, str) and not content.strip():
        content = None
    raw_tc = msg.get("tool_calls")
    tool_calls = _parse_tool_calls_from_response(raw_tc)
    if not content and not tool_calls:
        log.warning(
            "openrouter_with_tools empty assistant message model=%s finish_reason=%s "
            "message_keys=%s native_finish_reason=%s",
            model,
            finish_reason,
            list(msg.keys()),
            choice0.get("native_finish_reason"),
        )
    return (content, tool_calls)


async def call_ollama_with_tools(
    model: str,
    messages: list[dict],
    tools: list[dict],
) -> LLMWithToolsResult:
    """Ollama 带 tools 的调用。部分模型支持；不支持时退化为无 tool_calls。"""
    # Ollama 部分版本 / 模型支持 tools，格式与 OpenAI 类似
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages_with_tools_to_payload(messages),
        "stream": False,
        "tools": tools,
    }
    url = f"{settings.OLLAMA_BASE}/api/chat"
    r = await _httpx_post_json(
        url,
        headers=None,
        json_body=payload,
        timeout=OLLAMA_HTTP_TIMEOUT_S,
        upstream="Ollama",
    )
    if r.status_code >= 400:
        raise RuntimeError(f"[502] Ollama error {r.status_code}: {r.text}")
    data = _read_response_json(r, upstream="Ollama")
    msg = data.get("message", {})
    content = (msg.get("content") or "").strip() or None
    raw_tc = msg.get("tool_calls")
    tool_calls = _parse_tool_calls_from_response(raw_tc)
    return (content, tool_calls)


async def call_llm_with_tools(
    model_source: str,
    messages: list[dict],
    tools: list[dict],
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
) -> LLMWithToolsResult:
    """带 tools 的 LLM 调用；返回 (content 或 None, tool_calls 或 None)。

    Deprecated for Agent runtime (Pydantic AI + ``pa_tools``). Kept for tests and ad-hoc tooling.
    """
    src = (model_source or "cloud").lower()
    if src == "local":
        model = local_model_id or settings.OLLAMA_MODEL
    elif src == "cloud":
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY missing")
        model = cloud_model_id or settings.OPENROUTER_MODEL
    else:
        raise ValueError(f"Unknown modelSource: {model_source}")

    n_msg, n_chars = _dict_message_stats(messages)
    log.info(
        "llm_with_tools start source=%s model=%s messages=%d content_chars=%d tools=%d",
        src,
        model,
        n_msg,
        n_chars,
        len(tools),
    )
    t0 = time.perf_counter()
    try:
        if src == "local":
            content, tool_calls = await call_ollama_with_tools(
                model=model, messages=messages, tools=tools
            )
        else:
            content, tool_calls = await call_openrouter_with_tools(
                api_key=settings.OPENROUTER_API_KEY,
                model=model,
                messages=messages,
                tools=tools,
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        has_tools = bool(tool_calls)
        content_len = len(content) if content else 0
        log.info(
            "llm_with_tools done source=%s model=%s elapsed_ms=%.2f has_tool_calls=%s content_chars=%d",
            src,
            model,
            elapsed_ms,
            has_tools,
            content_len,
        )
        log_llm_call(
            call="with_tools",
            model_source=src,
            model=model,
            duration_ms=elapsed_ms,
            messages=messages,
            tools=tools,
            result=build_result_payload(content=content, tool_calls=tool_calls),
        )
        return (content, tool_calls)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.exception(
            "llm_with_tools failed source=%s model=%s elapsed_ms=%.2f",
            src,
            model,
            elapsed_ms,
        )
        log_llm_call(
            call="with_tools",
            model_source=src,
            model=model,
            duration_ms=elapsed_ms,
            messages=messages,
            tools=tools,
            error=build_error_payload(e),
        )
        raise


def _messages_are_dict_shape(messages: LLMPlainMessages) -> bool:
    """非空时用首条类型区分 Message 列表与 dict 列表（禁止混排）。"""
    if not messages:
        return False
    if isinstance(messages[0], dict):
        return True
    return False


@overload
async def call_llm(
    model_source: str,
    messages: list[Message],
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
) -> str: ...


@overload
async def call_llm(
    model_source: str,
    messages: list[dict[str, Any]],
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
) -> str: ...


async def call_llm(
    model_source: str,
    messages: LLMPlainMessages,
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
) -> str:
    """根据 model_source 调用本地或云端 LLM。

    ``messages`` 可为 ``Message``（普通 prompt）或 OpenAI-compatible ``dict``
    （含 assistant ``tool_calls`` / ``role=tool`` 等），二者不得混在同一列表内。
    dict 路径为普通 chat 请求，不附加 ``tools`` / ``tool_choice``。
    """
    src = (model_source or "cloud").lower()
    if src == "local":
        model = local_model_id or settings.OLLAMA_MODEL
    elif src == "cloud":
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY missing")
        model = cloud_model_id or settings.OPENROUTER_MODEL
    else:
        raise ValueError(f"Unknown modelSource: {model_source}")

    dict_mode = _messages_are_dict_shape(messages)
    if dict_mode:
        dict_messages = messages  # type: ignore[assignment]
        n_msg, n_chars = _dict_message_stats(dict_messages)
    else:
        msg_objs = messages  # type: ignore[assignment]
        n_msg, n_chars = _message_stats(msg_objs)

    log.info(
        "llm call start source=%s model=%s messages=%d content_chars=%d dict_messages=%s",
        src,
        model,
        n_msg,
        n_chars,
        dict_mode,
    )
    t0 = time.perf_counter()
    try:
        if dict_mode:
            dict_messages = messages  # type: ignore[assignment]
            if src == "local":
                out = await call_ollama_chat_dict(model=model, messages=dict_messages)
            else:
                out = await call_openrouter_chat_dict(
                    api_key=settings.OPENROUTER_API_KEY,
                    model=model,
                    messages=dict_messages,
                )
        else:
            msg_objs = messages  # type: ignore[assignment]
            if src == "local":
                out = await call_ollama(model=model, messages=msg_objs)
            else:
                out = await call_openrouter(
                    api_key=settings.OPENROUTER_API_KEY,
                    model=model,
                    messages=msg_objs,
                )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "llm call done source=%s model=%s elapsed_ms=%.2f response_chars=%d",
            src,
            model,
            elapsed_ms,
            len(out or ""),
        )
        log_llm_call(
            call="plain",
            model_source=src,
            model=model,
            duration_ms=elapsed_ms,
            messages=messages,
            result=build_result_payload(content=out),
        )
        return out
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.exception(
            "llm call failed source=%s model=%s elapsed_ms=%.2f",
            src,
            model,
            elapsed_ms,
        )
        log_llm_call(
            call="plain",
            model_source=src,
            model=model,
            duration_ms=elapsed_ms,
            messages=messages,
            error=build_error_payload(e),
        )
        raise
