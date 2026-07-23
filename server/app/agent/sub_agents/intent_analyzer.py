"""Intent 子代理：批量 LLM 分类回填 TableProfile.topic/description/granularity。

设计（context-analyzer 收尾项，见 .cursor/plans/intent-analyzer-semantic-fields.plan.md）：

- 单次批量调用覆盖 ``state.data_context`` 全部表；按 ``table_id`` + 结构签名（列名/
  类型/行数）做进程内缓存，未命中的才进 prompt，命中的直接复用。
- fail-open：分类失败/超时/结构化校验失败时保持三字段为 ``None``，记录 warning，
  不阻塞 ``llm_decide``。
- 回填后刷新 transcript 里已注入的 Data profile 消息（context_analyzer 早前注入的
  那条），否则 llm_decide 读到的还是回填前的旧文本。
"""
from __future__ import annotations

from pydantic_ai.settings import ModelSettings

from app.agent.context_assembler import refresh_data_profile_message
from app.agent.state import AgentState
from app.logging_config import get_logger
from app.models.table_models import TableIntent, TableIntentBatch, TableProfile
from app.services.llm import OPENROUTER_HTTP_TIMEOUT_CHAT_S
from app.services.llm_pydantic_ai import create_pa_agent

logger = get_logger("agent.intent_analyzer")

# 意图分类是轻量结构化输出，不复用为工具调用设计的 OPENROUTER_HTTP_TIMEOUT_TOOLS_S。
# 目前直接借用聊天场景超时，没有独立配置——有实测延迟数据显示不合适前不要拆分。
INTENT_TIMEOUT_S = OPENROUTER_HTTP_TIMEOUT_CHAT_S

_INTENT_INSTRUCTIONS = (
    "You classify spreadsheet tables from their column statistics. For each table "
    "given, infer: a short topic (a few words), a one-sentence description of what "
    "each row represents, and the row granularity (e.g. 'one row per order', "
    "'daily aggregate'). If you cannot confidently infer a field from the given "
    "statistics, leave it null rather than guessing."
)

# 进程内缓存：table_id + 结构签名 → 已分类的 TableIntent。不持久化，跨进程重启即失效。
_INTENT_CACHE: dict[str, TableIntent] = {}


def reset_intent_cache_for_tests() -> None:
    """测试专用：清空进程内意图分类缓存。"""
    _INTENT_CACHE.clear()


def _structure_signature(profile: TableProfile) -> int:
    """列名+类型+行数的结构签名；结构不变则复用语义标签，变了则视为新表重分类。"""
    return hash(
        (
            tuple(c.name for c in profile.columns),
            tuple(c.inferred_type for c in profile.columns),
            profile.total_row_count,
        )
    )


def _cache_key(table_id: str | None, profile: TableProfile) -> str | None:
    """``table_id`` 缺失（``TableContext`` 无 id 的边界情况）时返回 None，跳过缓存。"""
    if not table_id:
        return None
    return f"{table_id}:{_structure_signature(profile)}"


def format_table_profile_for_intent(profile: TableProfile) -> str:
    """表统计摘要 → intent 分类 prompt 片段。

    刻意不包含 ``profile.topic/description/granularity`` 本身——避免把上一轮
    （可能是错的）分类结果喂回模型形成自我强化的错误。
    """
    lines = [f'Table "{profile.table_name}" ({profile.total_row_count} rows):']
    for c in profile.columns:
        parts = [
            f"- {c.name}: {c.inferred_type}",
            f"{c.null_ratio:.0%} null",
            f"{c.distinct_count} distinct",
        ]
        if c.min_val is not None and c.max_val is not None:
            parts.append(f"range {c.min_val}–{c.max_val}")
        if c.top_values:
            tv = ", ".join(f"{v} ({n})" for v, n in c.top_values)
            parts.append(f"top: {tv}")
        lines.append(", ".join(parts))
    return "\n".join(lines)


async def classify_table_intents(
    tables: list[TableProfile],
    table_ids: dict[str, str | None],
    model_source: str,
    *,
    cloud_model_id: str | None = None,
    local_model_id: str | None = None,
) -> list[TableIntent]:
    """批量分类未命中缓存的表。

    返回顺序为「缓存命中」+「本次分类」，不保证与输入 ``tables`` 顺序一致——
    调用方按 ``table_name`` 做 join，顺序不重要。
    """
    if not tables:
        return []

    cached: list[TableIntent] = []
    to_classify: list[TableProfile] = []
    for t in tables:
        key = _cache_key(table_ids.get(t.table_name), t)
        hit = _INTENT_CACHE.get(key) if key is not None else None
        if hit is not None:
            cached.append(hit)
        else:
            to_classify.append(t)

    if not to_classify:
        return cached

    agent = create_pa_agent(
        model_source,
        cloud_model_id=cloud_model_id,
        local_model_id=local_model_id,
        instructions=_INTENT_INSTRUCTIONS,
        result_type=TableIntentBatch,
    )
    prompt = "\n\n".join(format_table_profile_for_intent(t) for t in to_classify)
    result = await agent.run(
        prompt, model_settings=ModelSettings(timeout=INTENT_TIMEOUT_S)
    )

    by_name = {t.table_name: t for t in to_classify}
    classified: list[TableIntent] = []
    for intent in result.output.tables:
        src = by_name.get(intent.table_name)
        if src is None:
            logger.info(
                "intent_analyzer: dropping unknown table_name %r from LLM output",
                intent.table_name,
            )
            continue
        classified.append(intent)
        key = _cache_key(table_ids.get(intent.table_name), src)
        if key is not None:
            _INTENT_CACHE[key] = intent

    return cached + classified


async def analyze_intent(state: AgentState) -> AgentState:
    """在 ``llm_decide`` 之前执行：批量分类回填语义字段并刷新 Data profile 消息。

    @param state: 当前 Agent 状态（含 ``data_context``）。
    @return: 增强后的 state；无 ``data_context``/无表或分类失败时原样返回。
    """
    dc = state.data_context
    if not dc or not dc.tables:
        return state

    table_ids = {t.name: t.table_id for t in state.tables}
    try:
        intents = await classify_table_intents(
            dc.tables,
            table_ids,
            state.model_source,
            cloud_model_id=state.cloud_model_id,
            local_model_id=state.local_model_id,
        )
    except Exception:
        logger.warning(
            "intent_analyzer: classify failed, fields left None", exc_info=True
        )
        return state

    by_name = {i.table_name: i for i in intents}
    new_tables = []
    for t in dc.tables:
        intent = by_name.get(t.table_name)
        if intent is None:
            new_tables.append(t)
            continue
        new_tables.append(
            t.model_copy(
                update={
                    "topic": intent.topic,
                    "description": intent.description,
                    "granularity": intent.granularity,
                }
            )
        )

    new_dc = dc.model_copy(update={"tables": new_tables})
    state = state.model_copy(update={"data_context": new_dc})
    return refresh_data_profile_message(state)
