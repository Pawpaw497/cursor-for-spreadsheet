import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "./llm";
import {
  debouncedSaveBackendSessionChat,
  flushDebouncedBackendSessionChatSave,
  loadBackendSessionChat,
  saveBackendSessionChat
} from "./backendSessionChatStorage";

const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("sessionStorage", {
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

describe("backendSessionChatStorage", () => {
  const bootId = "boot-abc";
  const workspaceKey = "workspace:builtin:sample-xlsx";

  it("round-trips chat messages per boot id and workspace", () => {
    const messages: ChatMessage[] = [
      {
        id: "m1",
        sessionId: bootId,
        role: "user",
        content: "hi",
        createdAt: "2026-01-01T00:00:00.000Z",
        source: "live"
      }
    ];
    saveBackendSessionChat(bootId, workspaceKey, messages);
    expect(loadBackendSessionChat(bootId, workspaceKey)).toEqual(messages);
    expect(loadBackendSessionChat("other-boot", workspaceKey)).toEqual([]);
  });

  it("debounced save persists after delay", () => {
    vi.useFakeTimers();
    debouncedSaveBackendSessionChat(bootId, workspaceKey, []);
    expect(loadBackendSessionChat(bootId, workspaceKey)).toEqual([]);

    debouncedSaveBackendSessionChat(bootId, workspaceKey, [
      {
        id: "m2",
        sessionId: bootId,
        role: "assistant",
        content: "ok",
        createdAt: "2026-01-01T00:00:01.000Z",
        source: "live"
      }
    ]);
    vi.advanceTimersByTime(500);
    flushDebouncedBackendSessionChatSave();

    expect(loadBackendSessionChat(bootId, workspaceKey)).toHaveLength(1);
  });
});
