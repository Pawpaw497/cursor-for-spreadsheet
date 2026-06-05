/**
 * Minimal SSE consumer for POST /api/agent-stream (mirrors server orchestrator events).
 */
import { generateTraceId, logError, logInfo } from "./logger";

const API_BASE = "http://localhost:8787";

export type AgentStreamEventKind =
  | "tool_call"
  | "tool_result"
  | "plan_done"
  | "preview_ready"
  | "finish"
  | "clarification";

export type AgentStreamEvent = {
  kind: AgentStreamEventKind;
  data: Record<string, unknown>;
};

export type AgentClarificationHistoryPayload = {
  question: string;
  options?: string[] | null;
  context?: string | null;
  state?: Record<string, unknown>;
};

export type TechnicalClarificationHistoryEntry = {
  id: number;
  prompt: string;
  payload: Record<string, unknown>;
  plan: null;
  diff: null;
  createdAt: string;
  modelSource: "cloud" | "local";
  modelId: string | null;
  modelTag?: string;
  mode: "agent_clarification";
  clarification: AgentClarificationHistoryPayload;
};

export type ConsumeAgentStreamOpts = {
  body: Record<string, unknown>;
  traceId?: string;
  sessionId?: string;
  signal?: AbortSignal;
  onEvent?: (event: AgentStreamEvent) => void;
  /** When set, append a technical-history row on terminal clarification. */
  onClarification?: (payload: AgentClarificationHistoryPayload) => void;
};

function parseSseChunk(buffer: string): { events: AgentStreamEvent[]; rest: string } {
  const events: AgentStreamEvent[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    if (!block.trim()) continue;
    let eventName: AgentStreamEventKind | null = null;
    let dataLine: string | null = null;
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) {
        eventName = line.slice(7).trim() as AgentStreamEventKind;
      } else if (line.startsWith("data: ")) {
        dataLine = line.slice(6);
      }
    }
    if (!eventName || dataLine == null) continue;
    try {
      events.push({ kind: eventName, data: JSON.parse(dataLine) as Record<string, unknown> });
    } catch {
      // skip malformed chunk
    }
  }
  return { events, rest };
}

/** Build a History-tab row for agent clarification terminal events. */
export function buildClarificationTechnicalHistoryEntry(
  clarification: AgentClarificationHistoryPayload,
  opts: {
    nextId: number;
    prompt: string;
    requestPayload: Record<string, unknown>;
    modelSource: "cloud" | "local";
    modelId: string | null;
    modelTag?: string;
  }
): TechnicalClarificationHistoryEntry {
  return {
    id: opts.nextId,
    prompt: opts.prompt,
    payload: opts.requestPayload,
    plan: null,
    diff: null,
    createdAt: new Date().toLocaleString(),
    modelSource: opts.modelSource,
    modelId: opts.modelId,
    modelTag: opts.modelTag,
    mode: "agent_clarification",
    clarification
  };
}

/**
 * POST /api/agent-stream and parse SSE until the stream closes.
 * Terminal events: plan_done, preview_ready, clarification, finish.
 */
export async function consumeAgentStream(
  opts: ConsumeAgentStreamOpts
): Promise<AgentStreamEvent[]> {
  const traceId = opts.traceId ?? generateTraceId();
  const collected: AgentStreamEvent[] = [];
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/api/agent-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opts.body),
      signal: opts.signal
    });
  } catch (e) {
    logError("agent_stream_fetch_failed", { traceId, error: String(e) });
    throw e;
  }
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`agent-stream ${resp.status}: ${txt}`);
  }
  if (!resp.body) {
    throw new Error("agent-stream response has no body");
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.rest;
    for (const ev of parsed.events) {
      collected.push(ev);
      opts.onEvent?.(ev);
      if (ev.kind === "clarification") {
        const payload: AgentClarificationHistoryPayload = {
          question: String(ev.data.question ?? ""),
          options: (ev.data.options as string[] | null | undefined) ?? null,
          context: (ev.data.context as string | null | undefined) ?? null,
          state: (ev.data.state as Record<string, unknown> | undefined) ?? undefined
        };
        opts.onClarification?.(payload);
        logInfo("agent_stream_clarification", { traceId, question: payload.question });
      }
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseChunk(`${buffer}\n\n`);
    for (const ev of parsed.events) {
      collected.push(ev);
      opts.onEvent?.(ev);
    }
  }

  logInfo("agent_stream_done", { traceId, eventCount: collected.length });
  return collected;
}

/** Dev helper: append clarification row to an in-memory conversations list. */
export function appendClarificationTechnicalHistory(
  conversations: TechnicalClarificationHistoryEntry[],
  entry: TechnicalClarificationHistoryEntry
): TechnicalClarificationHistoryEntry[] {
  return [entry, ...conversations];
}

declare global {
  interface Window {
    __spreadsheetCursorConsumeAgentStream?: typeof consumeAgentStream;
    __spreadsheetCursorBuildClarificationHistoryEntry?: typeof buildClarificationTechnicalHistoryEntry;
  }
}

if (typeof window !== "undefined") {
  window.__spreadsheetCursorConsumeAgentStream = consumeAgentStream;
  window.__spreadsheetCursorBuildClarificationHistoryEntry = buildClarificationTechnicalHistoryEntry;
}
