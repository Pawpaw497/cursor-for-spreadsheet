export const BUILTIN_SAMPLE_WORKSPACE_KEY = "workspace:builtin:sample-xlsx";
export const STORAGE_KEY_PREFIX = "spreadsheet-cursor:workspace:";

const STORAGE_VERSION = 2;
const LEGACY_STORAGE_VERSION = 1;
const MAX_CONVERSATIONS = 30;
const SAVE_DEBOUNCE_MS = 500;

export type StoredConversationEntry = {
  id: number;
  prompt: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  plan: any | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  diff: any | null;
  createdAt: string;
  modelSource: "cloud" | "local";
  modelId: string | null;
  modelTag?: string;
};

export type WorkspaceHistoryPayload = {
  version: number;
  conversations: StoredConversationEntry[];
};

function storageKey(workspaceKey: string): string {
  return `${STORAGE_KEY_PREFIX}${workspaceKey}`;
}

function shortModelId(modelId: string | null): string {
  if (!modelId) return "unknown";
  const parts = modelId.split("/");
  return parts[parts.length - 1] || modelId;
}

/** e.g. `cloud-Auto`, `local-llama3` */
export function formatModelTag(
  modelSource: "cloud" | "local",
  modelId: string | null,
  modelLabel?: string
): string {
  const suffix = modelLabel?.trim() || shortModelId(modelId);
  return `${modelSource}-${suffix}`;
}

export async function hashFileToWorkspaceKey(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  const hex = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `workspace:file:${hex}`;
}

function truncateConversations(
  conversations: StoredConversationEntry[]
): StoredConversationEntry[] {
  if (conversations.length <= MAX_CONVERSATIONS) {
    return conversations;
  }
  if (typeof console !== "undefined" && console.warn) {
    console.warn(
      `[workspaceHistory] Truncating conversations from ${conversations.length} to ${MAX_CONVERSATIONS}`
    );
  }
  return conversations.slice(0, MAX_CONVERSATIONS);
}

function parseStoredPayload(raw: string): WorkspaceHistoryPayload | null {
  try {
    const parsed = JSON.parse(raw) as {
      version?: number;
      conversations?: StoredConversationEntry[];
      chatMessages?: unknown;
    };
    const version = parsed.version;
    if (version !== STORAGE_VERSION && version !== LEGACY_STORAGE_VERSION) {
      return null;
    }
    return {
      version: STORAGE_VERSION,
      conversations: Array.isArray(parsed.conversations) ? parsed.conversations : []
    };
  } catch {
    return null;
  }
}

export function loadWorkspaceHistory(
  workspaceKey: string
): WorkspaceHistoryPayload | null {
  if (typeof localStorage === "undefined") {
    return null;
  }
  const raw = localStorage.getItem(storageKey(workspaceKey));
  if (!raw) return null;
  return parseStoredPayload(raw);
}

export function saveWorkspaceHistory(
  workspaceKey: string,
  payload: Pick<WorkspaceHistoryPayload, "conversations">
): void {
  if (typeof localStorage === "undefined") {
    return;
  }
  const body: WorkspaceHistoryPayload = {
    version: STORAGE_VERSION,
    conversations: truncateConversations(payload.conversations)
  };
  try {
    localStorage.setItem(storageKey(workspaceKey), JSON.stringify(body));
  } catch (e) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn("[workspaceHistory] save failed", e);
    }
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let pendingSave: {
  workspaceKey: string;
  payload: Pick<WorkspaceHistoryPayload, "conversations">;
} | null = null;

export function debouncedSaveWorkspaceHistory(
  workspaceKey: string,
  payload: Pick<WorkspaceHistoryPayload, "conversations">
): void {
  pendingSave = { workspaceKey, payload };
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (pendingSave) {
      saveWorkspaceHistory(pendingSave.workspaceKey, pendingSave.payload);
      pendingSave = null;
    }
  }, SAVE_DEBOUNCE_MS);
}

export function flushDebouncedWorkspaceHistorySave(): void {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (pendingSave) {
    saveWorkspaceHistory(pendingSave.workspaceKey, pendingSave.payload);
    pendingSave = null;
  }
}

export function workspaceHistoryHasContent(workspaceKey: string): boolean {
  const cached = loadWorkspaceHistory(workspaceKey);
  if (!cached) return false;
  return cached.conversations.length > 0;
}
