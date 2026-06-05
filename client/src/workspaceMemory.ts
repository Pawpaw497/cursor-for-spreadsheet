import { formatClarificationAssistantContent } from "./clarification";
import type { ChatMessage } from "./llm";
import type { Diff, Plan, PreviewRecord } from "./types";
import {
  CHAT_STORAGE_KEY_PREFIX,
  loadBackendSessionChat
} from "./backendSessionChatStorage";
import {
  formatModelTag,
  loadWorkspaceHistory,
  type StoredConversationEntry
} from "./workspaceHistoryStorage";

export const MEMORY_STORAGE_KEY_PREFIX = "spreadsheet-cursor:memory:v1:";
export const MEMORY_VERSION = 1;
const SAVE_DEBOUNCE_MS = 500;
const MAX_APPLY_LOG = 30;
const MAX_AGENT_TURNS = 48;
const MAX_SUMMARY_ENTRIES = 3;
const MAX_SUMMARY_CHARS = 3200;

export type AgentTurn = {
  role: "user" | "assistant";
  content: string;
};

export type AppliedPlanEntry = {
  prompt: string;
  intent: string;
  stepTypes: string[];
  addedColumns: string[];
  modifiedColumns: string[];
  tableNames: string[];
  appliedAt: string;
  modelTag: string;
};

export type SessionMeta = {
  sessionId: string;
  lastServerBootId: string | null;
  schemaFingerprint: string | null;
};

export type WorkspaceMemory = {
  version: number;
  chatTranscript: ChatMessage[];
  agentTranscript: AgentTurn[];
  applyLog: AppliedPlanEntry[];
  previewHistory: PreviewRecord[];
  appliedPlansSummary: string;
  sessionMeta: SessionMeta;
};

function storageKey(workspaceKey: string): string {
  return `${MEMORY_STORAGE_KEY_PREFIX}${workspaceKey}`;
}

function newSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `sess-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function emptyWorkspaceMemory(): WorkspaceMemory {
  return {
    version: MEMORY_VERSION,
    chatTranscript: [],
    agentTranscript: [],
    applyLog: [],
    previewHistory: [],
    appliedPlansSummary: "",
    sessionMeta: {
      sessionId: newSessionId(),
      lastServerBootId: null,
      schemaFingerprint: null
    }
  };
}

function parseMemory(raw: string): WorkspaceMemory | null {
  try {
    const parsed = JSON.parse(raw) as Partial<WorkspaceMemory>;
    if (parsed.version !== MEMORY_VERSION) {
      return null;
    }
    const base = emptyWorkspaceMemory();
    return {
      version: MEMORY_VERSION,
      chatTranscript: Array.isArray(parsed.chatTranscript)
        ? (parsed.chatTranscript as ChatMessage[])
        : [],
      agentTranscript: Array.isArray(parsed.agentTranscript)
        ? (parsed.agentTranscript as AgentTurn[])
        : [],
      applyLog: Array.isArray(parsed.applyLog)
        ? (parsed.applyLog as AppliedPlanEntry[])
        : [],
      previewHistory: Array.isArray(parsed.previewHistory)
        ? (parsed.previewHistory as PreviewRecord[])
        : [],
      appliedPlansSummary:
        typeof parsed.appliedPlansSummary === "string" ? parsed.appliedPlansSummary : "",
      sessionMeta: {
        sessionId:
          typeof parsed.sessionMeta?.sessionId === "string" &&
          parsed.sessionMeta.sessionId.trim()
            ? parsed.sessionMeta.sessionId
            : newSessionId(),
        lastServerBootId:
          typeof parsed.sessionMeta?.lastServerBootId === "string"
            ? parsed.sessionMeta.lastServerBootId
            : parsed.sessionMeta?.lastServerBootId === null
              ? null
              : null,
        schemaFingerprint:
          typeof parsed.sessionMeta?.schemaFingerprint === "string"
            ? parsed.sessionMeta.schemaFingerprint
            : null
      }
    };
  } catch {
    return null;
  }
}

function tableNamesFromPlan(plan: Plan): string[] {
  const names = new Set<string>();
  const steps = Array.isArray(plan.steps) ? plan.steps : [];
  for (const step of steps) {
    const s = step as { table?: string; left?: string; right?: string; name?: string; source?: string; resultTable?: string };
    for (const key of ["table", "left", "right", "name", "source", "resultTable"] as const) {
      const v = s[key];
      if (typeof v === "string" && v.trim()) {
        names.add(v.trim());
      }
    }
  }
  return [...names];
}

export function createApplyLogEntry(opts: {
  prompt: string;
  plan: Plan;
  diff: Diff | null;
  modelTag: string;
  tableNames?: string[];
}): AppliedPlanEntry {
  const steps = Array.isArray(opts.plan.steps) ? opts.plan.steps : [];
  return {
    prompt: opts.prompt.trim(),
    intent: (opts.plan.intent ?? "").trim(),
    stepTypes: steps.map((step) => (step as { action?: string }).action ?? "step"),
    addedColumns: opts.diff?.addedColumns ?? [],
    modifiedColumns: opts.diff?.modifiedColumns ?? [],
    tableNames: opts.tableNames?.length ? opts.tableNames : tableNamesFromPlan(opts.plan),
    appliedAt: new Date().toISOString(),
    modelTag: opts.modelTag
  };
}

export function formatApplyLogEntryForSummary(entry: AppliedPlanEntry): string {
  const lines: string[] = [];
  if (entry.prompt) {
    lines.push(`Prompt: ${entry.prompt}`);
  }
  if (entry.intent) {
    lines.push(entry.intent);
  }
  if (entry.stepTypes.length) {
    lines.push(`Steps: ${entry.stepTypes.join(", ")}`);
  }
  const cols = [...entry.addedColumns, ...entry.modifiedColumns];
  if (cols.length) {
    lines.push(`Columns: ${cols.join(", ")}`);
  }
  if (entry.tableNames.length) {
    lines.push(`Tables: ${entry.tableNames.join(", ")}`);
  }
  return lines.join("\n");
}

export function buildAppliedPlansSummaryFromLog(
  applyLog: AppliedPlanEntry[],
  maxEntries = MAX_SUMMARY_ENTRIES
): string {
  const recent = applyLog.slice(0, maxEntries);
  let summary = recent.map(formatApplyLogEntryForSummary).filter(Boolean).join("\n---\n");
  if (summary.length > MAX_SUMMARY_CHARS) {
    summary = summary.slice(0, MAX_SUMMARY_CHARS).trimEnd() + "\n…";
  }
  return summary;
}

export function chatToAgentTranscript(chat: ChatMessage[]): AgentTurn[] {
  return chat
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => {
      if (m.role === "assistant" && m.meta?.kind === "clarification") {
        return {
          role: "assistant" as const,
          content: formatClarificationAssistantContent(
            m.content,
            typeof m.meta.context === "string" ? m.meta.context : null
          )
        };
      }
      return {
        role: m.role as "user" | "assistant",
        content: m.content
      };
    });
}

export function appendClarificationToTranscript(
  memory: WorkspaceMemory,
  question: string,
  context: string | null | undefined,
  answer: string
): WorkspaceMemory {
  const turns: AgentTurn[] = [
    {
      role: "assistant",
      content: formatClarificationAssistantContent(question, context)
    },
    { role: "user", content: answer }
  ];
  return {
    ...memory,
    agentTranscript: truncateAgentTranscript([...memory.agentTranscript, ...turns])
  };
}

export function buildAgentHistoryFromTranscript(
  agentTranscript: AgentTurn[],
  maxTurns = 24
): AgentTurn[] {
  return agentTranscript.slice(-maxTurns);
}

function conversationToApplyLogEntry(conv: StoredConversationEntry): AppliedPlanEntry | null {
  if (!conv.plan) {
    return null;
  }
  return createApplyLogEntry({
    prompt: conv.prompt,
    plan: conv.plan as Plan,
    diff: conv.diff as Diff | null,
    modelTag: conv.modelTag ?? formatModelTag(conv.modelSource, conv.modelId)
  });
}

function migrateChatFromSessionStorage(
  workspaceKey: string,
  currentBootId: string | null
): ChatMessage[] {
  if (currentBootId) {
    const current = loadBackendSessionChat(currentBootId, workspaceKey);
    if (current.length > 0) {
      return current;
    }
  }
  if (typeof sessionStorage === "undefined") {
    return [];
  }
  const suffix = `:${workspaceKey}`;
  let best: ChatMessage[] = [];
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i);
    if (!key?.startsWith(CHAT_STORAGE_KEY_PREFIX) || !key.endsWith(suffix)) {
      continue;
    }
    try {
      const raw = sessionStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as unknown;
      if (!Array.isArray(parsed)) continue;
      const messages = parsed as ChatMessage[];
      if (messages.length > best.length) {
        best = messages;
      }
    } catch {
      // skip corrupt legacy keys
    }
  }
  return best;
}

function migrateApplyLogFromWorkspaceHistory(workspaceKey: string): AppliedPlanEntry[] {
  const history = loadWorkspaceHistory(workspaceKey);
  if (!history?.conversations.length) {
    return [];
  }
  const entries: AppliedPlanEntry[] = [];
  for (const conv of history.conversations) {
    const entry = conversationToApplyLogEntry(conv);
    if (entry) {
      entries.unshift(entry);
    }
  }
  return entries.slice(0, MAX_APPLY_LOG);
}

function migrateLegacyStores(
  workspaceKey: string,
  currentBootId: string | null
): WorkspaceMemory {
  const memory = emptyWorkspaceMemory();
  const chat = migrateChatFromSessionStorage(workspaceKey, currentBootId);
  memory.chatTranscript = chat;
  memory.agentTranscript = chatToAgentTranscript(chat);
  memory.applyLog = migrateApplyLogFromWorkspaceHistory(workspaceKey);
  memory.appliedPlansSummary = buildAppliedPlansSummaryFromLog(memory.applyLog);
  if (currentBootId) {
    memory.sessionMeta.lastServerBootId = currentBootId;
  }
  return memory;
}

export function loadWorkspaceMemory(
  workspaceKey: string,
  currentBootId: string | null = null
): WorkspaceMemory {
  if (typeof localStorage === "undefined" || !workspaceKey) {
    return emptyWorkspaceMemory();
  }
  const raw = localStorage.getItem(storageKey(workspaceKey));
  if (!raw) {
    return migrateLegacyStores(workspaceKey, currentBootId);
  }
  const parsed = parseMemory(raw);
  if (!parsed) {
    return migrateLegacyStores(workspaceKey, currentBootId);
  }
  if (
    parsed.chatTranscript.length === 0 &&
    parsed.agentTranscript.length === 0 &&
    parsed.applyLog.length === 0
  ) {
    const legacy = migrateLegacyStores(workspaceKey, currentBootId);
    if (
      legacy.chatTranscript.length > 0 ||
      legacy.agentTranscript.length > 0 ||
      legacy.applyLog.length > 0
    ) {
      saveWorkspaceMemory(workspaceKey, legacy);
      return legacy;
    }
  }
  return parsed;
}

function truncateAgentTranscript(transcript: AgentTurn[]): AgentTurn[] {
  if (transcript.length <= MAX_AGENT_TURNS) {
    return transcript;
  }
  return transcript.slice(-MAX_AGENT_TURNS);
}

export function saveWorkspaceMemory(workspaceKey: string, memory: WorkspaceMemory): void {
  if (typeof localStorage === "undefined" || !workspaceKey) {
    return;
  }
  const body: WorkspaceMemory = {
    ...memory,
    version: MEMORY_VERSION,
    agentTranscript: truncateAgentTranscript(memory.agentTranscript),
    applyLog: memory.applyLog.slice(0, MAX_APPLY_LOG)
  };
  try {
    localStorage.setItem(storageKey(workspaceKey), JSON.stringify(body));
  } catch (e) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn("[workspaceMemory] save failed", e);
    }
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let pendingSave: { workspaceKey: string; memory: WorkspaceMemory } | null = null;

export function debouncedSaveWorkspaceMemory(
  workspaceKey: string,
  memory: WorkspaceMemory
): void {
  pendingSave = { workspaceKey, memory };
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (pendingSave) {
      saveWorkspaceMemory(pendingSave.workspaceKey, pendingSave.memory);
      pendingSave = null;
    }
  }, SAVE_DEBOUNCE_MS);
}

export function flushDebouncedWorkspaceMemorySave(): void {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (pendingSave) {
    saveWorkspaceMemory(pendingSave.workspaceKey, pendingSave.memory);
    pendingSave = null;
  }
}

export function appendApplyLogEntry(
  memory: WorkspaceMemory,
  entry: AppliedPlanEntry
): WorkspaceMemory {
  const applyLog = [entry, ...memory.applyLog].slice(0, MAX_APPLY_LOG);
  return {
    ...memory,
    applyLog,
    appliedPlansSummary: buildAppliedPlansSummaryFromLog(applyLog)
  };
}

export function syncAgentTranscriptFromChat(
  memory: WorkspaceMemory,
  chatTranscript: ChatMessage[]
): WorkspaceMemory {
  return {
    ...memory,
    chatTranscript,
    agentTranscript: chatToAgentTranscript(chatTranscript)
  };
}

export function updateSessionBootId(
  memory: WorkspaceMemory,
  serverBootId: string | null
): WorkspaceMemory {
  return {
    ...memory,
    sessionMeta: {
      ...memory.sessionMeta,
      lastServerBootId: serverBootId
    }
  };
}

export function formatLastApplyHint(entry: AppliedPlanEntry | undefined): string {
  if (!entry) {
    return "";
  }
  const parts: string[] = [];
  if (entry.intent) {
    parts.push(entry.intent);
  } else if (entry.stepTypes.length) {
    parts.push(entry.stepTypes.join(", "));
  }
  const cols = [...entry.addedColumns, ...entry.modifiedColumns];
  if (cols.length) {
    parts.push(cols.join(", "));
  }
  return parts.join(" · ") || entry.prompt || "Applied plan";
}

export function workspaceMemoryHasContent(workspaceKey: string): boolean {
  const memory = loadWorkspaceMemory(workspaceKey);
  return (
    memory.chatTranscript.length > 0 ||
    memory.applyLog.length > 0 ||
    memory.agentTranscript.length > 0
  );
}
