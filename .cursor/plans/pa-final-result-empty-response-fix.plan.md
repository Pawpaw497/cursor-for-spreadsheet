---
name: pa-final-result-empty-response-fix
overview: Fix PA final_result tool-call argument coercion so invalid structured Plan output reports plan_validation_failed instead of empty_response.
todos:
  - id: coerce-final-result-args
    content: "Add _coerce_plan_from_final_result_args(args: Any) -> Plan in server/app/agent/pa_decision.py for Plan, dict, and JSON string args via extract_json, json.loads, and Plan.model_validate"
    status: completed
  - id: surface-final-result-error
    content: Extend PaTurnResult and partition_tool_calls to return final_result_error only when no final_result parsed successfully, with short truncated log-safe text
    status: completed
  - id: finish-plan-validation-failed
    content: Update _extract_model_turn and _finish_terminal_turn so final_result_error becomes FinishAction reason plan_validation_failed before true empty_response fallback
    status: completed
  - id: backend-pa-tests
    content: Update server/tests/test_pa_structured_plan.py tuple unpacking and cover string final_result args, invalid string args, final_result_error, and preserved empty_response behavior
    status: completed
  - id: frontend-detail-reason
    content: Update client/src/llm.ts to display FastAPI detail.reason for object details and add minimal Vitest coverage
    status: completed
  - id: readme-empty-response-note
    content: Clarify README empty-response notes for call_llm /api/plan retry, PA final_result plan_validation_failed, and true PA empty_response
    status: completed
  - id: focused-verification
    content: Run server pytest for PA structured/decision tests and client npm test or the narrow added client test
    status: completed
isProject: false
---

# PA final_result empty_response fix

## Problem

After the LangGraph/Pydantic AI migration, `/api/agent` can return `422 {detail:{kind:"error",reason:"empty_response"}}` for prompts such as "Add a column total_price = price * quantity". Logs show `pa_decision final_result validation failed ... input_type=str`.

The model did return a Pydantic AI `final_result` tool call, but `ToolCallPart.args` was a JSON string or malformed string rather than a `dict` or `Plan`. `partition_tool_calls` swallowed that validation failure. Because the assistant text was empty, `_finish_terminal_turn` misreported the turn as `empty_response`.

This is different from the pre-migration empty-response fix in `server/app/services/llm.py` and legacy `decision.py`: that path handled truly empty OpenRouter assistant content and text JSON parsing/retry. It does not cover PA `final_result` tool-call args.

## Implementation plan

1. Backend: add `_coerce_plan_from_final_result_args(args: Any) -> Plan` in `server/app/agent/pa_decision.py`. Support `Plan`, `dict`, and JSON `str` via `extract_json` + `json.loads` + `Plan.model_validate`. Do not add a new LLM retry for invalid `final_result`.
2. Backend: extend `PaTurnResult` with `final_result_error: str | None = None`. Make `partition_tool_calls` return `(regular_tool_parts, structured_plan, final_result_error)`. Prefer a successful `structured_plan`; only retain an error when no `final_result` parsed successfully. Keep error text short/truncated with `_truncate_for_log` and do not return raw args in HTTP detail.
3. Backend: update `_extract_model_turn` and `_finish_terminal_turn` so `final_result_error` returns `FinishAction` reason starting with `plan_validation_failed:` before falling through to `empty_response`. Preserve true `empty_response` for no tool, no text, and no `final_result_error`.
4. Backend tests: update existing tuple unpacking in `server/tests/test_pa_structured_plan.py`; add tests for string `final_result` args, invalid string args, and `final_result_error` not becoming `empty_response`; preserve `test_pa_decision_empty_response`.
5. Frontend: update `client/src/llm.ts` `errorMessageFromResponse` so FastAPI detail objects like `{kind, reason}` show `detail.reason` instead of a JSON blob. Add minimal Vitest coverage via `requestAgentProjectPlan`/fetch mock or a small exported parser if that is clearly lower-risk.
6. README: correct the Agent empty response note to distinguish `call_llm` `/api/plan*` 502 empty content retry from PA `/api/agent` invalid `final_result` -> 422 `plan_validation_failed` and true empty turn -> 422 `empty_response`.
7. Verification: `cd server && uv run pytest tests/test_pa_structured_plan.py tests/test_pa_decision.py -q`; `cd client && npm test -- --run` or the narrow client test if one is added.

## Non-goals

- Do not modify LangGraph orchestrator/SSE parity.
- Do not change `AGENT_PA_PLAN_JSON_FALLBACK` default.
- Do not add a second LLM retry loop for invalid `final_result`.
- Do not change the default OpenRouter model.
