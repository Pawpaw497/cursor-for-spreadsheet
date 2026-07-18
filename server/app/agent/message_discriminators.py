"""共享消息判别器：识别 transcript 中的特殊 user 消息。

memory_compaction（保护/尾链）、context_analyzer（定位/去重）、
context_assembler（渲染前缀）统一从本模块导入，避免跨模块私有依赖。
本模块只依赖 stdlib，不参与任何循环导入。
"""
from __future__ import annotations

from typing import Any

# Data profile 消息的身份前缀：renderer 输出以它开头，判别/去重/compaction 保护
# 一律经 is_data_profile_message 识别（禁止在调用方硬编码该字符串）。
DATA_PROFILE_PREFIX = "Data profile:\n"


def is_table_context_message(msg: dict[str, Any]) -> bool:
    """schema/table-context user 消息（单表或多表）。"""
    if msg.get("role") != "user":
        return False
    content = str(msg.get("content") or "")
    return "Spreadsheet schema:" in content or "Project has multiple tables:" in content


def is_selection_context_message(msg: dict[str, Any]) -> bool:
    """selection / workspace rules user 消息。"""
    if msg.get("role") != "user":
        return False
    content = str(msg.get("content") or "")
    return "Current selection:" in content or "Workspace rules:" in content


def is_data_profile_message(msg: dict[str, Any]) -> bool:
    """context_analyzer 注入的 Data profile user 消息。"""
    if msg.get("role") != "user":
        return False
    return str(msg.get("content") or "").startswith(DATA_PROFILE_PREFIX)
