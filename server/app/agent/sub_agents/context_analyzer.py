"""Context 子代理：从 store 读全量 rows 计算 DataContext 并注入 Data profile 消息。

注入规则（R1，2026-07-15 定稿）：仅当 ``state.messages`` 中已存在 schema 消息
（``is_table_context_message`` 命中）时注入，插入位置为该消息之前、每次重新
定位；无 schema 消息（legacy 懒构建路径）则跳过注入但照常填 ``data_context``，
绝不代替消息组装层 materialize schema。重跑时先移除旧 profile 再注入新的。
"""
from __future__ import annotations

import logging
import time

from app.agent.context_assembler import build_data_context_text
from app.agent.message_discriminators import (
    is_data_profile_message,
    is_table_context_message,
)
from app.agent.sub_agents.profile_builder import build_table_profile
from app.models.agent_models import AgentState
from app.models.table_models import DataContext, TableProfile
from app.services.data_store import TableNotFoundError, get_data_store

logger = logging.getLogger(__name__)


def _build_profiles(state: AgentState) -> list[TableProfile]:
    profiles: list[TableProfile] = []
    missing: list[str] = []
    store = get_data_store()
    for t in state.tables:
        if not t.table_id:
            logger.info("context_analyzer: no table_id for %r, skip profile", t.name)
            continue
        try:
            t0 = time.perf_counter()
            stored = store.read_table(t.table_id)
            read_ms = (time.perf_counter() - t0) * 1000
        except TableNotFoundError:
            logger.info(
                "context_analyzer: table %r (%s) not in store, skip profile",
                t.name,
                t.table_id,
            )
            missing.append(t.name)
            continue
        t1 = time.perf_counter()
        profiles.append(build_table_profile(t.name, t.schema, stored.rows))
        profile_ms = (time.perf_counter() - t1) * 1000
        logger.debug(
            "context_analyzer: %r rows=%d read=%.1fms profile=%.1fms",
            t.name,
            len(stored.rows),
            read_ms,
            profile_ms,
        )
    if missing and profiles:
        # 部分表缺失但仍产出 partial DataContext：单条汇总，便于排查静默缺列。
        logger.warning(
            "context_analyzer: partial DataContext, missing tables: %s",
            ", ".join(missing),
        )
    return profiles


def analyze_context(state: AgentState) -> AgentState:
    """在 plan_generator 之前执行：填充 ``state.data_context`` 并注入 Data profile。

    @param state: 当前 Agent 状态（含多表与 messages）。
    @return: 增强后的 state；无可用 table_id 时原样返回。
    """
    profiles = _build_profiles(state)
    if not profiles:
        # 首轮成功、后续 store 失效的场景：清掉过期的 data_context 与旧 profile 消息，
        # 避免 LLM 拿到 stale 统计。
        messages = [m for m in state.messages if not is_data_profile_message(m)]
        if state.data_context is None and len(messages) == len(state.messages):
            return state
        return state.model_copy(
            update={"data_context": None, "messages": messages}
        )

    state = state.model_copy(update={"data_context": DataContext(tables=profiles)})

    text = build_data_context_text(state.data_context)
    if not text:
        return state

    messages = [m for m in state.messages if not is_data_profile_message(m)]
    schema_idx = next(
        (i for i, m in enumerate(messages) if is_table_context_message(m)), None
    )
    if schema_idx is None:
        logger.info(
            "context_analyzer: no schema message in transcript, skip profile injection"
        )
        # 旧 profile 消息若存在（schema 消息后来消失的罕见场景）也一并清除，
        # 避免 stale profile 留在 transcript 里。
        if len(messages) != len(state.messages):
            return state.model_copy(update={"messages": messages})
        return state

    messages.insert(schema_idx, {"role": "user", "content": text})
    return state.model_copy(update={"messages": messages})
