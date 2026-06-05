import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "./llm";
import { CHAT_STORAGE_KEY_PREFIX } from "./backendSessionChatStorage";
import { STORAGE_KEY_PREFIX } from "./workspaceHistoryStorage";
import {
  MEMORY_STORAGE_KEY_PREFIX,
  appendApplyLogEntry,
  appendClarificationToTranscript,
  buildAppliedPlansSummaryFromLog,
  buildAgentHistoryFromTranscript,
  chatToAgentTranscript,
  createApplyLogEntry,
  debouncedSaveWorkspaceMemory,
  flushDebouncedWorkspaceMemorySave,
  loadWorkspaceMemory,
  saveWorkspaceMemory,
  syncAgentTranscriptFromChat
} from "./workspaceMemory";

const localStore = new Map<string, string>();
const sessionStore = new Map<string, string>();

beforeEach(() => {
  localStore.clear();
  sessionStore.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => localStore.get(k) ?? null,
    setItem: (k: string, v: string) => {
      localStore.set(k, v);
    },
    removeItem: (k: string) => {
      localStore.delete(k);
    }
  });
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => sessionStore.get(k) ?? null,
    setItem: (k: string, v: string) => {
      sessionStore.set(k, v);
    },
    removeItem: (k: string) => {
      sessionStore.delete(k);
    },
    key: (i: number) => [...sessionStore.keys()][i] ?? null,
    get length() {
      return sessionStore.size;
    }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const workspaceKey = "workspace:builtin:sample-xlsx";

describe("workspaceMemory", () => {
  it("round-trips memory payload in localStorage", () => {
    const chat: ChatMessage[] = [
      {
        id: "m1",
        sessionId: "boot",
        role: "user",
        content: "add total",
        createdAt: "2026-01-01T00:00:00.000Z",
        source: "live"
      }
    ];
    saveWorkspaceMemory(workspaceKey, {
      version: 1,
      chatTranscript: chat,
      agentTranscript: [{ role: "user", content: "add total" }],
      applyLog: [],
      previewHistory: [],
      appliedPlansSummary: "",
      sessionMeta: {
        sessionId: "sess-1",
        lastServerBootId: "boot-a",
        schemaFingerprint: null
      }
    });

    const loaded = loadWorkspaceMemory(workspaceKey, "boot-b");
    expect(loaded.chatTranscript).toEqual(chat);
    expect(loaded.sessionMeta.sessionId).toBe("sess-1");
    expect(localStore.has(`${MEMORY_STORAGE_KEY_PREFIX}${workspaceKey}`)).toBe(true);
  });

  it("migrates sessionStorage chat when v1 memory is empty", () => {
    const bootId = "boot-old";
    sessionStore.set(
      `${CHAT_STORAGE_KEY_PREFIX}${bootId}:${workspaceKey}`,
      JSON.stringify([
        {
          id: "m1",
          sessionId: bootId,
          role: "user",
          content: "legacy chat",
          createdAt: "2026-01-01T00:00:00.000Z",
          source: "live"
        }
      ])
    );

    const loaded = loadWorkspaceMemory(workspaceKey, bootId);
    expect(loaded.chatTranscript).toHaveLength(1);
    expect(loaded.chatTranscript[0]!.content).toBe("legacy chat");
    expect(loaded.agentTranscript).toEqual([
      { role: "user", content: "legacy chat" }
    ]);
  });

  it("migrates workspace history conversations into applyLog", () => {
    localStore.set(`${STORAGE_KEY_PREFIX}${workspaceKey}`, JSON.stringify({
      version: 2,
      conversations: [
        {
          id: 1,
          prompt: "join tables",
          payload: {},
          plan: {
            intent: "Join orders",
            steps: [{ action: "join_tables", left: "A", right: "B" }]
          },
          diff: { addedColumns: ["total"], modifiedColumns: [], removedColumns: [] },
          createdAt: "2026-01-01",
          modelSource: "cloud",
          modelId: "auto",
          modelTag: "cloud-Auto"
        }
      ]
    }));

    const loaded = loadWorkspaceMemory(workspaceKey, null);
    expect(loaded.applyLog).toHaveLength(1);
    expect(loaded.applyLog[0]!.intent).toBe("Join orders");
    expect(loaded.appliedPlansSummary).toContain("Join orders");
  });

  it("builds rolling applied summary from apply log", () => {
    const entry = createApplyLogEntry({
      prompt: "add total",
      plan: {
        intent: "Add total column",
        steps: [{ action: "add_column", name: "total", expression: "a+b" }]
      },
      diff: { addedColumns: ["total"], modifiedColumns: [], removedColumns: [] },
      modelTag: "cloud-Auto"
    });
    const summary = buildAppliedPlansSummaryFromLog([entry]);
    expect(summary).toContain("Add total column");
    expect(summary).toContain("total");
  });

  it("appendApplyLogEntry prepends newest entry", () => {
    const first = createApplyLogEntry({
      prompt: "one",
      plan: { intent: "First", steps: [] },
      diff: null,
      modelTag: "cloud-Auto"
    });
    const second = createApplyLogEntry({
      prompt: "two",
      plan: { intent: "Second", steps: [] },
      diff: null,
      modelTag: "cloud-Auto"
    });
    let memory = appendApplyLogEntry(
      {
        version: 1,
        chatTranscript: [],
        agentTranscript: [],
        applyLog: [first],
        previewHistory: [],
        appliedPlansSummary: "",
        sessionMeta: {
          sessionId: "s",
          lastServerBootId: null,
          schemaFingerprint: null
        }
      },
      second
    );
    expect(memory.applyLog[0]!.intent).toBe("Second");
    expect(memory.appliedPlansSummary).toContain("Second");
  });

  it("chatToAgentTranscript formats clarification assistant turns", () => {
    const chat: ChatMessage[] = [
      {
        id: "a1",
        sessionId: "boot",
        role: "assistant",
        content: "Which table?",
        createdAt: "t",
        source: "live",
        meta: { kind: "clarification", context: "Ambiguous steps" }
      }
    ];
    expect(chatToAgentTranscript(chat)).toEqual([
      { role: "assistant", content: "[Clarification] Which table?\nAmbiguous steps" }
    ]);
  });

  it("appendClarificationToTranscript appends formatted Q/A turns", () => {
    const memory = {
      version: 1,
      chatTranscript: [],
      agentTranscript: [{ role: "user" as const, content: "add column" }],
      applyLog: [],
      previewHistory: [],
      appliedPlansSummary: "",
      sessionMeta: {
        sessionId: "s",
        lastServerBootId: null,
        schemaFingerprint: null
      }
    };
    const next = appendClarificationToTranscript(memory, "Which table?", null, "Sheet2");
    expect(next.agentTranscript).toHaveLength(3);
    expect(next.agentTranscript[1]!.content).toBe("[Clarification] Which table?");
    expect(next.agentTranscript[2]!.content).toBe("Sheet2");
  });

  it("syncAgentTranscriptFromChat mirrors user and assistant turns", () => {
    const chat: ChatMessage[] = [
      {
        id: "u1",
        sessionId: "boot",
        role: "user",
        content: "hi",
        createdAt: "t",
        source: "live"
      },
      {
        id: "a1",
        sessionId: "boot",
        role: "assistant",
        content: "hello",
        createdAt: "t",
        source: "live"
      }
    ];
    const synced = syncAgentTranscriptFromChat(
      {
        version: 1,
        chatTranscript: [],
        agentTranscript: [],
        applyLog: [],
        previewHistory: [],
        appliedPlansSummary: "",
        sessionMeta: {
          sessionId: "s",
          lastServerBootId: null,
          schemaFingerprint: null
        }
      },
      chat
    );
    expect(synced.agentTranscript).toEqual(chatToAgentTranscript(chat));
    expect(buildAgentHistoryFromTranscript(synced.agentTranscript, 24)).toHaveLength(2);
  });

  it("debounced save persists after delay", () => {
    vi.useFakeTimers();
    debouncedSaveWorkspaceMemory(workspaceKey, {
      version: 1,
      chatTranscript: [],
      agentTranscript: [],
      applyLog: [],
      previewHistory: [],
      appliedPlansSummary: "",
      sessionMeta: {
        sessionId: "s",
        lastServerBootId: null,
        schemaFingerprint: null
      }
    });
    expect(loadWorkspaceMemory(workspaceKey).chatTranscript).toHaveLength(0);

    vi.advanceTimersByTime(500);
    flushDebouncedWorkspaceMemorySave();

    expect(localStore.has(`${MEMORY_STORAGE_KEY_PREFIX}${workspaceKey}`)).toBe(true);
  });
});
