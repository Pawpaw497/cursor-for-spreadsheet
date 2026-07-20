"""Agent 首轮 / 当前轮 user 消息构建（含表 schema 与样本），供 PA 与 initial_state 共用。"""
from __future__ import annotations

from typing import Any

from app.models.agent_models import AgentState, TableContext
from app.services.prompts import ProjectPrompt, SpreadsheetPrompt


def build_initial_user_message_from_tables(
    user_prompt: str,
    tables: list[TableContext],
) -> dict[str, Any]:
    """构建含表格上下文的 user dict（不含 system）。"""
    if len(tables) == 1:
        prompt = SpreadsheetPrompt()
        t = tables[0]
        user_content = prompt.build_user_content(user_prompt, t.schema)
    else:
        prompt = ProjectPrompt()
        tables_data = [
            {"name": t.name, "schema": t.schema}
            for t in tables
        ]
        user_content = prompt.build_user_content(user_prompt, tables_data)
    return {"role": "user", "content": user_content}


def build_initial_user_message(state: AgentState) -> dict[str, Any]:
    """从 AgentState 构建当前轮完整 user 消息。"""
    return build_initial_user_message_from_tables(state.user_prompt, state.tables)
