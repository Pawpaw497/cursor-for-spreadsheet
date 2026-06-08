import { describe, expect, it } from "vitest";

import type { WorkspaceMemory } from "./workspaceMemory";
import { mergeWorkspaceMemory, workspaceMemoryIsEmpty } from "./sessionMemorySync";

function memory(partial: Partial<WorkspaceMemory> & Pick<WorkspaceMemory, "sessionMeta">): WorkspaceMemory {
  return {
    version: 1,
    chatTranscript: [],
    agentTranscript: [],
    applyLog: [],
    previewHistory: [],
    appliedPlansSummary: "",
    ...partial
  };
}

describe("sessionMemorySync", () => {
  it("restores from server when local is empty", () => {
    const sessionId = "00000000-0000-4000-8000-000000000001";
    const local = memory({
      sessionMeta: {
        sessionId,
        lastServerBootId: "boot-a",
        schemaFingerprint: null
      }
    });
    const remote = memory({
      chatTranscript: [
        {
          id: "m1",
          sessionId,
          role: "user",
          content: "hello",
          createdAt: "2026-06-01T00:00:00.000Z",
          source: "live"
        }
      ],
      agentTranscript: [{ role: "user", content: "hello" }],
      sessionMeta: {
        sessionId,
        lastServerBootId: null,
        schemaFingerprint: null
      }
    });
    const merged = mergeWorkspaceMemory(local, remote, "2026-06-02T00:00:00.000Z");
    expect(merged.chatTranscript).toHaveLength(1);
    expect(merged.sessionMeta.sessionId).toBe(sessionId);
    expect(merged.sessionMeta.lastServerBootId).toBe("boot-a");
  });

  it("prefers newer remote timestamp", () => {
    const sessionId = "00000000-0000-4000-8000-000000000002";
    const local = memory({
      chatTranscript: [
        {
          id: "m1",
          sessionId,
          role: "user",
          content: "local",
          createdAt: "2026-06-01T00:00:00.000Z",
          source: "live"
        }
      ],
      sessionMeta: {
        sessionId,
        lastServerBootId: null,
        schemaFingerprint: null,
        localUpdatedAt: "2026-06-01T00:00:00.000Z"
      }
    });
    const remote = memory({
      chatTranscript: [
        {
          id: "m2",
          sessionId,
          role: "user",
          content: "remote",
          createdAt: "2026-06-03T00:00:00.000Z",
          source: "live"
        }
      ],
      sessionMeta: {
        sessionId,
        lastServerBootId: null,
        schemaFingerprint: null
      }
    });
    const merged = mergeWorkspaceMemory(local, remote, "2026-06-03T00:00:00.000Z");
    expect(merged.chatTranscript[0]?.content).toBe("remote");
  });

  it("keeps local when local is newer", () => {
    const sessionId = "00000000-0000-4000-8000-000000000003";
    const local = memory({
      agentTranscript: [{ role: "user", content: "local wins" }],
      sessionMeta: {
        sessionId,
        lastServerBootId: null,
        schemaFingerprint: null,
        localUpdatedAt: "2026-06-05T00:00:00.000Z"
      }
    });
    const remote = memory({
      agentTranscript: [{ role: "user", content: "remote stale" }],
      sessionMeta: {
        sessionId,
        lastServerBootId: null,
        schemaFingerprint: null
      }
    });
    const merged = mergeWorkspaceMemory(local, remote, "2026-06-04T00:00:00.000Z");
    expect(merged.agentTranscript[0]?.content).toBe("local wins");
  });

  it("detects empty memory", () => {
    expect(
      workspaceMemoryIsEmpty(
        memory({
          sessionMeta: {
            sessionId: "s",
            lastServerBootId: null,
            schemaFingerprint: null
          }
        })
      )
    ).toBe(true);
  });
});
