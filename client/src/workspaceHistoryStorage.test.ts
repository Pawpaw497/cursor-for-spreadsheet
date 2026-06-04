import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BUILTIN_SAMPLE_WORKSPACE_KEY,
  STORAGE_KEY_PREFIX,
  debouncedSaveWorkspaceHistory,
  flushDebouncedWorkspaceHistorySave,
  loadWorkspaceHistory,
  saveWorkspaceHistory,
  formatModelTag
} from "./workspaceHistoryStorage";

const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v);
    },
    removeItem: (k: string) => {
      store.delete(k);
    }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("formatModelTag", () => {
  it("uses label when provided", () => {
    expect(formatModelTag("cloud", "openrouter/auto", "Auto")).toBe("cloud-Auto");
  });

  it("falls back to short model id", () => {
    expect(formatModelTag("local", "ollama/llama3", undefined)).toBe("local-llama3");
  });
});

describe("workspaceHistoryStorage", () => {
  it("round-trips conversations only", () => {
    const conversations = [
      {
        id: 1,
        prompt: "p",
        payload: { x: 1 },
        plan: null,
        diff: null,
        createdAt: "2026-01-01",
        modelSource: "cloud" as const,
        modelId: "auto",
        modelTag: "cloud-Auto"
      }
    ];

    saveWorkspaceHistory(BUILTIN_SAMPLE_WORKSPACE_KEY, { conversations });
    const loaded = loadWorkspaceHistory(BUILTIN_SAMPLE_WORKSPACE_KEY);

    expect(loaded).not.toBeNull();
    expect(loaded!.version).toBe(2);
    expect(loaded!.conversations).toEqual(conversations);
    expect(store.has(`${STORAGE_KEY_PREFIX}${BUILTIN_SAMPLE_WORKSPACE_KEY}`)).toBe(true);
  });

  it("ignores legacy v1 chatMessages field", () => {
    store.set(`${STORAGE_KEY_PREFIX}legacy`, JSON.stringify({
      version: 1,
      chatMessages: [{ id: "m1", content: "old" }],
      conversations: []
    }));
    const loaded = loadWorkspaceHistory("legacy");
    expect(loaded).not.toBeNull();
    expect(loaded!.conversations).toEqual([]);
  });

  it("truncates conversations to the most recent 30 entries", () => {
    const conversations = Array.from({ length: 35 }, (_, i) => ({
      id: i + 1,
      prompt: `p${i}`,
      payload: {},
      plan: null,
      diff: null,
      createdAt: "t",
      modelSource: "cloud" as const,
      modelId: null
    }));

    saveWorkspaceHistory("workspace:file:abc", { conversations });
    const loaded = loadWorkspaceHistory("workspace:file:abc");

    expect(loaded!.conversations).toHaveLength(30);
    expect(loaded!.conversations[0]!.id).toBe(1);
    expect(loaded!.conversations[29]!.id).toBe(30);
  });

  it("debounced save persists after delay", () => {
    vi.useFakeTimers();
    debouncedSaveWorkspaceHistory(BUILTIN_SAMPLE_WORKSPACE_KEY, {
      conversations: [
        {
          id: 1,
          prompt: "x",
          payload: {},
          plan: null,
          diff: null,
          createdAt: "t",
          modelSource: "local",
          modelId: null
        }
      ]
    });
    expect(loadWorkspaceHistory(BUILTIN_SAMPLE_WORKSPACE_KEY)).toBeNull();

    vi.advanceTimersByTime(500);
    flushDebouncedWorkspaceHistorySave();

    expect(loadWorkspaceHistory(BUILTIN_SAMPLE_WORKSPACE_KEY)?.conversations).toHaveLength(1);
  });
});
