import type { ChatMessage } from "./llm";

export const CHAT_STORAGE_KEY_PREFIX = "spreadsheet-cursor:chat:";

const SAVE_DEBOUNCE_MS = 500;

function storageKey(serverBootId: string, workspaceKey: string): string {
  return `${CHAT_STORAGE_KEY_PREFIX}${serverBootId}:${workspaceKey}`;
}

export function loadBackendSessionChat(
  serverBootId: string,
  workspaceKey: string
): ChatMessage[] {
  if (typeof sessionStorage === "undefined" || !serverBootId || !workspaceKey) {
    return [];
  }
  try {
    const raw = sessionStorage.getItem(storageKey(serverBootId, workspaceKey));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as ChatMessage[]) : [];
  } catch {
    return [];
  }
}

export function saveBackendSessionChat(
  serverBootId: string,
  workspaceKey: string,
  chatMessages: ChatMessage[]
): void {
  if (typeof sessionStorage === "undefined" || !serverBootId || !workspaceKey) {
    return;
  }
  try {
    sessionStorage.setItem(
      storageKey(serverBootId, workspaceKey),
      JSON.stringify(chatMessages)
    );
  } catch (e) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn("[backendSessionChat] save failed", e);
    }
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let pendingSave: {
  serverBootId: string;
  workspaceKey: string;
  chatMessages: ChatMessage[];
} | null = null;

export function debouncedSaveBackendSessionChat(
  serverBootId: string,
  workspaceKey: string,
  chatMessages: ChatMessage[]
): void {
  pendingSave = { serverBootId, workspaceKey, chatMessages };
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (pendingSave) {
      saveBackendSessionChat(
        pendingSave.serverBootId,
        pendingSave.workspaceKey,
        pendingSave.chatMessages
      );
      pendingSave = null;
    }
  }, SAVE_DEBOUNCE_MS);
}

export function flushDebouncedBackendSessionChatSave(): void {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (pendingSave) {
    saveBackendSessionChat(
      pendingSave.serverBootId,
      pendingSave.workspaceKey,
      pendingSave.chatMessages
    );
    pendingSave = null;
  }
}
