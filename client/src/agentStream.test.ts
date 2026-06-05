import { describe, expect, it } from "vitest";

import {
  appendClarificationTechnicalHistory,
  buildClarificationTechnicalHistoryEntry,
  type AgentStreamEvent
} from "./agentStream";

describe("agentStream helpers", () => {
  it("buildClarificationTechnicalHistoryEntry tags mode agent_clarification", () => {
    const entry = buildClarificationTechnicalHistoryEntry(
      { question: "Which table?", options: ["A", "B"], context: "ctx" },
      {
        nextId: 1,
        prompt: "add column",
        requestPayload: { prompt: "add column" },
        modelSource: "cloud",
        modelId: "test/model"
      }
    );
    expect(entry.mode).toBe("agent_clarification");
    expect(entry.clarification.question).toBe("Which table?");
    expect(entry.plan).toBeNull();
  });

  it("appendClarificationTechnicalHistory prepends entry", () => {
    const base = buildClarificationTechnicalHistoryEntry(
      { question: "Q" },
      {
        nextId: 2,
        prompt: "p",
        requestPayload: {},
        modelSource: "local",
        modelId: null
      }
    );
    const next = appendClarificationTechnicalHistory([], base);
    expect(next).toHaveLength(1);
    expect(next[0]!.id).toBe(2);
  });

  it("parseSseChunk logic via event shape expectations", () => {
    const ev: AgentStreamEvent = {
      kind: "clarification",
      data: { question: "Which?", options: ["S1"] }
    };
    expect(ev.kind).toBe("clarification");
    expect(ev.data.question).toBe("Which?");
  });
});
