"""Pydantic AI agent tools: typed parameters and OpenAI-compatible schema (Phase 3)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from app.agent.state import TableContext
from app.services.tools import run_tool

AgentDepsT = TypeVar("AgentDepsT")

# pydantic-ai structured output tool name (not executed in Approach A).
PA_OUTPUT_TOOL_NAME = "final_result"


@dataclass(frozen=True, slots=True)
class PaAgentDeps:
    """Per-run deps injected into PA tools (tables from current AgentState)."""

    tables: list[TableContext]


class GetSchemaArgs(BaseModel):
    table_name: str | None = Field(
        default=None,
        description="Table name; omit to get the only table or all tables.",
    )


class GetColumnStatsArgs(BaseModel):
    table_name: str = Field(description="Table name.")
    column: str = Field(description="Column name.")


class ValidateExpressionArgs(BaseModel):
    expression: str = Field(
        description=(
            "JavaScript expression as (row) => expr; use exact schema column keys "
            "from the user message, e.g. row['单价'] * row['数量']."
        )
    )
    table_name: str | None = Field(
        default=None,
        description="Table name; omit for first table.",
    )


class ExecuteStepArgs(BaseModel):
    step: dict[str, Any] = Field(description="A single plan step object.")
    table_name: str | None = Field(
        default=None,
        description="Target table name (optional).",
    )


class RollbackLastStepArgs(BaseModel):
    """No parameters."""


class AskUserArgs(BaseModel):
    question: str = Field(description="Short clarification question for the user.")
    options: list[str] | None = Field(
        default=None,
        description="Optional choices (e.g. table names) for the user to pick from.",
    )
    context: str | None = Field(
        default=None,
        description="Optional brief context shown with the question.",
    )


ASK_USER_TOOL_NAME = "ask_user"


@dataclass(frozen=True, slots=True)
class PaToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]


PA_TOOL_DEFINITIONS: tuple[PaToolDefinition, ...] = (
    PaToolDefinition(
        name="get_schema",
        description=(
            "Get schema (column names and types) of a table or all tables. "
            "Use when you need to know column names or types."
        ),
        args_model=GetSchemaArgs,
    ),
    PaToolDefinition(
        name="get_column_stats",
        description=(
            "Get simple stats for a column (count, distinct, min/max if numeric) "
            "from full table data in the store."
        ),
        args_model=GetColumnStatsArgs,
    ),
    PaToolDefinition(
        name="validate_expression",
        description=(
            "Validate a JavaScript-like expression (e.g. for add_column) against "
            "the first row from store read_rows(table_id, 0, 1). Arguments must be "
            "a JSON object with \"expression\" using exact column keys from schema "
            "(not English aliases)."
        ),
        args_model=ValidateExpressionArgs,
    ),
    PaToolDefinition(
        name="execute_step",
        description=(
            "Execute a single plan step (demo stub). Use when you want to reason "
            "about step-wise execution; actual data mutation still happens in the "
            "frontend."
        ),
        args_model=ExecuteStepArgs,
    ),
    PaToolDefinition(
        name="rollback_last_step",
        description=(
            "Rollback last executed step (demo stub). Currently only a semantic hook; "
            "real rollback is handled in the frontend."
        ),
        args_model=RollbackLastStepArgs,
    ),
    PaToolDefinition(
        name=ASK_USER_TOOL_NAME,
        description=(
            "Ask the user a clarification question when intent is ambiguous. "
            "Use BEFORE outputting a plan when the target table or column is unclear."
        ),
        args_model=AskUserArgs,
    ),
)


def tool_names() -> list[str]:
    return [t.name for t in PA_TOOL_DEFINITIONS]


def _tool_description(name: str) -> str:
    return next(t.description for t in PA_TOOL_DEFINITIONS if t.name == name)


def _openai_parameters_schema(args_model: type[BaseModel]) -> dict[str, Any]:
    """Compact JSON Schema object for OpenAI ``tools[].function.parameters``."""
    schema = args_model.model_json_schema()
    params: dict[str, Any] = {"type": "object", "properties": schema.get("properties", {})}
    if schema.get("required"):
        params["required"] = schema["required"]
    return params


def build_openai_tools_spec() -> list[dict[str, Any]]:
    """OpenAI-compatible tool list (single source for legacy ``get_tools_spec_for_llm``)."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": _openai_parameters_schema(spec.args_model),
            },
        }
        for spec in PA_TOOL_DEFINITIONS
    ]


def _run_tool_from_args(
    ctx: RunContext[PaAgentDeps],
    tool_name: str,
    args: BaseModel,
) -> str:
    payload = args.model_dump(exclude_none=True)
    return run_tool(tool_name, payload, ctx.deps.tables)


def register_pa_agent_tools(agent: Agent[PaAgentDeps, Any]) -> None:
    """Register spreadsheet agent tools on a Pydantic AI ``Agent``."""

    @agent.tool(description=_tool_description("get_schema"))
    async def get_schema(
        ctx: RunContext[PaAgentDeps], table_name: str | None = None
    ) -> str:
        return _run_tool_from_args(
            ctx, "get_schema", GetSchemaArgs(table_name=table_name)
        )

    @agent.tool(description=_tool_description("get_column_stats"))
    async def get_column_stats(
        ctx: RunContext[PaAgentDeps], table_name: str, column: str
    ) -> str:
        return _run_tool_from_args(
            ctx,
            "get_column_stats",
            GetColumnStatsArgs(table_name=table_name, column=column),
        )

    @agent.tool(description=_tool_description("validate_expression"))
    async def validate_expression(
        ctx: RunContext[PaAgentDeps],
        expression: str,
        table_name: str | None = None,
    ) -> str:
        return _run_tool_from_args(
            ctx,
            "validate_expression",
            ValidateExpressionArgs(expression=expression, table_name=table_name),
        )

    @agent.tool(description=_tool_description("execute_step"))
    async def execute_step(
        ctx: RunContext[PaAgentDeps],
        step: dict[str, Any],
        table_name: str | None = None,
    ) -> str:
        return _run_tool_from_args(
            ctx,
            "execute_step",
            ExecuteStepArgs(step=step, table_name=table_name),
        )

    @agent.tool(description=_tool_description("rollback_last_step"))
    async def rollback_last_step(ctx: RunContext[PaAgentDeps]) -> str:
        return _run_tool_from_args(ctx, "rollback_last_step", RollbackLastStepArgs())
