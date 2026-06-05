import { describe, expect, it } from "vitest";

import {
  buildClarificationResumeHistory,
  buildClarificationResumeHistoryFromChat,
  buildClarificationResumePrompt,
  formatClarificationAssistantContent,
  truncatePromptAnchor
} from "./clarification";
import type { AgentTurn } from "./workspaceMemory";

describe("clarification helpers", () => {
  it("formats assistant clarification content with optional context", () => {
    expect(formatClarificationAssistantContent("Which table?")).toBe(
      "[Clarification] Which table?"
    );
    expect(formatClarificationAssistantContent("Which table?", "Ambiguous steps")).toBe(
      "[Clarification] Which table?\nAmbiguous steps"
    );
  });

  it("buildClarificationResumeHistory appends formatted turns", () => {
    const existing: AgentTurn[] = [{ role: "user", content: "add column" }];
    const next = buildClarificationResumeHistory(
      existing,
      "Which table?",
      "ctx",
      "Sheet2"
    );
    expect(next).toHaveLength(3);
    expect(next[1]).toEqual({
      role: "assistant",
      content: "[Clarification] Which table?\nctx"
    });
    expect(next[2]).toEqual({ role: "user", content: "Sheet2" });
  });

  it("buildClarificationResumeHistoryFromChat replaces trailing chat turns", () => {
    const chatHistory: AgentTurn[] = [
      { role: "user", content: "add column" },
      { role: "assistant", content: "Which table?" },
      { role: "user", content: "Sheet2" }
    ];
    const next = buildClarificationResumeHistoryFromChat(
      chatHistory,
      "Which table?",
      null,
      "Sheet2"
    );
    expect(next).toHaveLength(3);
    expect(next[1]!.content).toBe("[Clarification] Which table?");
    expect(next[2]!.content).toBe("Sheet2");
  });

  it("buildClarificationResumePrompt suffixes the original prompt", () => {
    expect(buildClarificationResumePrompt("add total", "Sheet2")).toBe(
      "add total\n\n[Clarification]\nSheet2"
    );
  });

  it("truncatePromptAnchor shortens long prompts", () => {
    const long = "a".repeat(100);
    expect(truncatePromptAnchor(long, 20)).toBe(`${"a".repeat(19)}…`);
    expect(truncatePromptAnchor("short")).toBe("short");
  });
});
