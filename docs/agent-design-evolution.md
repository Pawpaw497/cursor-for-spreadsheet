# Agent 架构演进：从 MVP 到生产级智能表格引擎

**文档状态：** 深度评估与演进建议（非 MVP 视角）  
**作者：** Senior Software Designer (Gemini 3 Flash)  
**日期：** 2026-07-06

## 1. 核心综述

在非 MVP 阶段，Agent 的核心挑战从「能否产出 Plan」转向「如何在海量数据、超长上下文、高频交互中保持**确定性、经济性与自进化能力**」。

通过对比 Claude Code（Anthropic 内部架构）与 Hermes Agent（Nous Research 开放架构），我们发现「带宽管理」与「任务解耦」是通往生产级的必经之路。本项目现有的 v2 计划是良好的起点，但需在**三层存储模型、辅模型异步化、以及技能复利**三个维度进行深度补强。

---

## 2. 竞品深度解构（非 MVP 特性）

### 2.1 Claude Code：极致的带宽与安全防御
Claude Code 的泄露源码展示了一个「重防御、轻负担」的工业级设计：

*   **三层存储模型 (Tiered Memory)**：
    *   **L1 (Index)**: `MEMORY.md` 仅存储指针和元数据，极度精简（<25KB）。
    *   **L2 (Topic Files)**: 具体的业务知识按需加载，避免 Context 污染。
    *   **L3 (Grep-only Logs)**: 原始日志永不全量读入，仅通过 `grep` 检索信号。
*   **YOLO 安全分类器 (Fast-Path Security)**：
    *   采用 64-token 的极速扫描（Stage 1）过滤 90% 的安全请求，仅对高危操作启动 4096-token 的深度推理（Stage 2）。
*   **AutoDream (REM Sleep)**：
    *   利用闲时进行「记忆整理」，将零散对话合并为结构化知识。

### 2.2 Hermes Agent：模块化与技能复利
Hermes 展示了如何通过工程化手段实现 Agent 的自增长：

*   **Skills 闭环 (Self-Improving Loop)**：
    *   Agent 在完成复杂任务后，自动提取「Transformation Recipe」（技能文档）。下次遇到相似任务时，直接加载规程而非重新推理。
*   **辅模型服务 (Auxiliary Client)**：
    *   将摘要、视觉、压缩等「非决策任务」剥离到独立客户端，支持并行调用与异构模型。
*   **ContextEngine 抽象**：
    *   将上下文管理逻辑从主循环中解耦，支持 A/B 测试不同的压缩与检索策略。

---

## 3. 架构对比与差距分析

| 维度 | 本项目 (v2 计划) | 生产级标杆 (Claude/Hermes) | 差距与风险 |
| :--- | :--- | :--- | :--- |
| **记忆模型** | `appliedPlansSummary` (LLM 刷新) | 三层存储 + 异步整理 | **摘要漂移风险**：单纯摘要易随轮次产生幻觉。 |
| **上下文管理** | 确定性 Compaction + Pre-plan 裁剪 | 动态 Topic 加载 + FTS 检索 | **大表瓶颈**：全量 Schema 注入在多表场景下会撑爆 Context。 |
| **任务编排** | 单一 ReAct 循环 (LangGraph) | 多 Agent Swarm + IPC 邮箱 | **复杂任务降级**：Join/Aggregate 等跨表任务在单循环中易出错。 |
| **性能优化** | Pre-plan 同步调用 (带超时) | 辅模型异步化 + 预加载 | **首包延迟**：同步 Pre-plan 仍会增加用户等待感。 |

---

## 4. 非 MVP 演进方案（对 v2 的补强）

基于上述分析，建议在 v2 计划的基础上，引入以下「非 MVP」补强项：

### 4.1 存储架构：从「摘要」转向「索引 + 事实」
*   **Replenishment**: 建立 `docs/workspaces/{id}/knowledge/` 目录。
*   **设计**: `appliedPlansSummary` 仅保留表名、列名索引。具体的「列含义」、「复杂公式逻辑」存入独立的 Topic Markdown 文件。
*   **收益**: 显著降低主 Planner 的 Token 消耗，提高多轮指代的准确性。

### 4.2 决策路径：引入「YOLO 快慢路径」
*   **Replenishment**: 在 `pre_plan_context` 之前增加一个极轻量（如 GPT-4o-mini 或同档）的 **Intent Classifier**。
*   **设计**: 
    *   **Fast Path**: 简单编辑（如「改个列名」）跳过 Pre-plan LLM，直接走规则模板。
    *   **Slow Path**: 复杂分析（如「合并两表并计算同比」）启动深度 Pre-plan。
*   **收益**: 简单操作响应时间缩短 500ms+，节省 API 成本。

### 4.3 技能复利：Transformation Recipes
*   **Replenishment**: 新增 `RecipeGenerator` 子代理。
*   **设计**: 当用户确认一个包含 3 个步骤以上的 Plan 且执行成功后，异步生成一个 Recipe。
*   **效果**: 用户下次说「按上次的逻辑处理新表」时，Agent 能够精准复现逻辑，而非凭记忆猜测。

### 4.4 基础设施：统一辅模型层 (Auxiliary Service)
*   **Replenishment**: 抽象 `app.services.aux_llm`。
*   **设计**: 统一管理 Pre-plan、Preview Summary、Clarification Scan 的调用。支持：
    *   **并发请求**: 同时启动 Pre-plan 和 Preview 准备。
    *   **模型异构**: 决策用主模型，辅助用轻量模型。
*   **收益**: 架构解耦，便于后续进行模型级 A/B 测试。

---

## 5. 实施路线图建议

1.  **Phase 1 (v2 Core)**: 完成 Pre-plan 裁剪与 Preview 摘要（解决「能用」）。
2.  **Phase 2 (Infrastructure)**: 落地 `Auxiliary Service` 与 YOLO 快慢路径（解决「快与省」）。
3.  **Phase 3 (Memory Evolution)**: 实施三层存储模型与 Topic Files（解决「长效」）。
4.  **Phase 4 (Self-Improvement)**: 引入 Recipes 闭环（解决「复利」）。

---

## 6. 结论

非 MVP 的 Agent 设计不应追求「更强的单一模型」，而应追求「更合理的带宽分配」与「更稳固的领域事实 (Ground Truth)」。通过借鉴 Claude Code 的带宽管理与 Hermes 的技能闭环，本项目可以从一个「表格对话框」进化为真正的「表格智能引擎」。
