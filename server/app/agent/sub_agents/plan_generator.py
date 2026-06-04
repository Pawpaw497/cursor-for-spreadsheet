"""Plan 生成阶段符号：与 ``pa_decision_step`` 同语义；LangGraph 中由 ``orchestrator`` 的 llm 节点承担。"""

# 与 pa_decision / Plan 校验解耦，避免重复维护。
# 若 future 在独立 LLM 链上生成 plan，可在此实现。
