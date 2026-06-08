import { describe, expect, it } from "vitest";
import { compactAgentTranscript, MAX_CHAT_TURNS } from "./memoryCompaction";
import type { AgentTurn, AppliedPlanEntry } from "./workspaceMemory";
import { buildAgentHistoryFromTranscript } from "./workspaceMemory";

function makePairs(count: number): AgentTurn[] {
  const turns: AgentTurn[] = [];
  for (let i = 0; i < count; i++) {
    turns.push({ role: "user", content: `user-${i}` });
    turns.push({ role: "assistant", content: `assistant-${i}` });
  }
  return turns;
}

describe("compactAgentTranscript", () => {
  it("returns transcript unchanged when within maxTurns", () => {
    const transcript = makePairs(5);
    expect(compactAgentTranscript(transcript, [], "", MAX_CHAT_TURNS)).toEqual(
      transcript
    );
  });

  it("collapses oldest turns with Earlier summary", () => {
    const transcript = makePairs(32);
    const applyLog: AppliedPlanEntry[] = [
      {
        prompt: "add total",
        intent: "Add total column",
        stepTypes: ["add_column"],
        addedColumns: ["total"],
        modifiedColumns: [],
        tableNames: ["Sheet1"],
        appliedAt: "2026-01-01T00:00:00.000Z",
        modelTag: "cloud:test"
      }
    ];
    const result = compactAgentTranscript(
      transcript,
      applyLog,
      "",
      MAX_CHAT_TURNS
    );
    expect(result.length).toBe(MAX_CHAT_TURNS + 1);
    expect(result[0].role).toBe("user");
    expect(result[0].content).toContain("Earlier in this workspace:");
    expect(result[0].content).toContain("Add total column");
    expect(result[result.length - 1].content).toBe("assistant-31");
  });

  it("prefers appliedPlansSummary over applyLog", () => {
    const transcript = makePairs(30);
    const result = compactAgentTranscript(
      transcript,
      [],
      "Pinned summary line",
      MAX_CHAT_TURNS
    );
    expect(result[0].content).toContain("Pinned summary line");
  });
});

describe("buildAgentHistoryFromTranscript", () => {
  it("uses compaction instead of blind slice", () => {
    const transcript = makePairs(30);
    const result = buildAgentHistoryFromTranscript(transcript, MAX_CHAT_TURNS, {
      applyLog: [],
      appliedPlansSummary: "from memory"
    });
    expect(result[0].content).toContain("Earlier in this workspace:");
    expect(result.length).toBeLessThanOrEqual(MAX_CHAT_TURNS + 1);
  });
});
