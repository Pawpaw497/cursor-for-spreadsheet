"""PA state adapters: message history and graph helpers."""
from __future__ import annotations

import json

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart

from app.agent.pa_state import (
    agent_to_graph,
    build_pa_message_history,
    dict_messages_to_pa_history,
    graph_to_agent,
    system_instructions_for_state,
    user_prompt_for_pa_run,
)
from app.models.agent_models import (
    AgentState,
    TableContext,
    initial_state_from_agent_project_request,
)
from app.models.plan import AgentProjectPlanRequest, ConversationTurn, TableInfo


def _table() -> TableContext:
    return TableContext(
        name="Sheet1",
        schema=[{"key": "a", "type": "string"}],
    )


def test_agent_to_graph_roundtrip() -> None:
    agent = AgentState(tables=[_table()], messages=[], user_prompt="hi")
    g = agent_to_graph(agent, scratch={"route": "end"})
    back = graph_to_agent(g)
    assert back.user_prompt == "hi"
    assert g["scratch"]["route"] == "end"


def test_system_instructions_single_vs_project() -> None:
    single = AgentState(tables=[_table()], messages=[], user_prompt="x")
    multi = AgentState(
        tables=[_table(), TableContext(name="T2", schema=[])],
        messages=[],
        user_prompt="x",
    )
    assert "Sheet1" in system_instructions_for_state(single) or len(
        system_instructions_for_state(single)
    ) > 50
    assert system_instructions_for_state(single) != system_instructions_for_state(multi)


def test_build_pa_message_history_empty() -> None:
    state = AgentState(tables=[_table()], messages=[], user_prompt="Add column x")
    assert build_pa_message_history(state) == []
    assert user_prompt_for_pa_run(state) is not None
    assert "Add column x" in (user_prompt_for_pa_run(state) or "")


def test_dict_messages_tool_chain() -> None:
    tid = "call_abc"
    msgs = [
        {"role": "user", "content": "do something"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tid,
                    "type": "function",
                    "function": {
                        "name": "get_schema",
                        "arguments": json.dumps({"table_name": "Sheet1"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": tid, "content": "{}"},
    ]
    hist = dict_messages_to_pa_history(msgs)
    assert len(hist) == 3
    assert isinstance(hist[0], ModelRequest)
    assert isinstance(hist[0].parts[0], UserPromptPart)
    assert isinstance(hist[1], ModelResponse)
    assert isinstance(hist[1].parts[0], ToolCallPart)
    assert hist[1].parts[0].tool_name == "get_schema"
    assert isinstance(hist[2], ModelRequest)
    assert isinstance(hist[2].parts[0], ToolReturnPart)
    assert hist[2].parts[0].tool_name == "get_schema"
    assert hist[2].parts[0].tool_call_id == tid


def test_initial_state_from_agent_project_request_history() -> None:
    req = AgentProjectPlanRequest(
        prompt="current",
        tables=[
            TableInfo(
                name="Sheet1",
                schema_=[{"key": "a", "type": "string"}],
                sampleRows=[{"a": "1"}],
            )
        ],
        history=[ConversationTurn(role="user", content="prior")],
        modelSource="cloud",
    )
    state = initial_state_from_agent_project_request(req)
    hist = build_pa_message_history(state)
    assert len(hist) >= 2
    assert user_prompt_for_pa_run(state) is None
