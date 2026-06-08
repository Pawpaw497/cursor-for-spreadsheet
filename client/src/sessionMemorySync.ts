import type { WorkspaceMemory } from "./workspaceMemory";

const API_BASE = "http://localhost:8787";
const SYNC_DEBOUNCE_MS = 800;

export type ServerSessionPayload = {
  sessionId: string;
  version: number;
  updatedAt: string;
  memory: WorkspaceMemory;
};

export type SessionSyncResult = {
  version: number;
  updatedAt: string;
};

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
}

export function workspaceMemoryIsEmpty(memory: WorkspaceMemory): boolean {
  return (
    memory.chatTranscript.length === 0 &&
    memory.agentTranscript.length === 0 &&
    memory.applyLog.length === 0
  );
}

/** Last-write-wins merge; browser-first when timestamps tie. */
export function mergeWorkspaceMemory(
  local: WorkspaceMemory,
  remote: WorkspaceMemory,
  remoteUpdatedAt: string
): WorkspaceMemory {
  const localEmpty = workspaceMemoryIsEmpty(local);
  const remoteEmpty = workspaceMemoryIsEmpty(remote);
  if (localEmpty && !remoteEmpty) {
    return {
      ...remote,
      sessionMeta: {
        ...remote.sessionMeta,
        sessionId: local.sessionMeta.sessionId,
        lastServerBootId: local.sessionMeta.lastServerBootId,
        localUpdatedAt: remoteUpdatedAt,
        serverUpdatedAt: remoteUpdatedAt
      }
    };
  }
  if (!localEmpty && remoteEmpty) {
    return local;
  }

  const localTs = parseTimestamp(local.sessionMeta.localUpdatedAt);
  const remoteTs = parseTimestamp(remoteUpdatedAt);
  if (remoteTs > localTs) {
    return {
      ...remote,
      sessionMeta: {
        ...remote.sessionMeta,
        sessionId: local.sessionMeta.sessionId,
        lastServerBootId: local.sessionMeta.lastServerBootId ?? remote.sessionMeta.lastServerBootId,
        localUpdatedAt: remoteUpdatedAt,
        serverUpdatedAt: remoteUpdatedAt
      }
    };
  }
  return local;
}

export async function hashWorkspaceKey(workspaceKey: string): Promise<string | null> {
  const key = workspaceKey.trim();
  if (!key || typeof crypto === "undefined" || !crypto.subtle) {
    return null;
  }
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function fetchServerSession(
  sessionId: string
): Promise<ServerSessionPayload | null> {
  const sid = sessionId.trim();
  if (!sid) return null;
  const resp = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sid)}`, {
    method: "GET",
    headers: { Accept: "application/json" }
  });
  if (resp.status === 404) {
    return null;
  }
  if (resp.status === 503) {
    return null;
  }
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`Session fetch failed (${resp.status}): ${txt}`);
  }
  return (await resp.json()) as ServerSessionPayload;
}

export async function pushServerSession(
  sessionId: string,
  memory: WorkspaceMemory,
  opts?: {
    projectId?: string | null;
    workspaceKey?: string | null;
    expectedVersion?: number | null;
  }
): Promise<SessionSyncResult | null> {
  const sid = sessionId.trim();
  if (!sid) return null;
  const workspaceKeyHash = opts?.workspaceKey
    ? await hashWorkspaceKey(opts.workspaceKey)
    : null;
  const resp = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sid)}`, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Session-ID": sid
    },
    body: JSON.stringify({
      memory: {
        ...memory,
        sessionMeta: {
          ...memory.sessionMeta,
          sessionId: sid
        }
      },
      projectId: opts?.projectId ?? undefined,
      workspaceKeyHash: workspaceKeyHash ?? undefined,
      localUpdatedAt: memory.sessionMeta.localUpdatedAt ?? undefined,
      expectedVersion: opts?.expectedVersion ?? undefined
    })
  });
  if (resp.status === 503) {
    return null;
  }
  if (resp.status === 409) {
    return null;
  }
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`Session sync failed (${resp.status}): ${txt}`);
  }
  const body = (await resp.json()) as ServerSessionPayload;
  return { version: body.version, updatedAt: body.updatedAt };
}

export function applyServerSyncMeta(
  memory: WorkspaceMemory,
  result: SessionSyncResult
): WorkspaceMemory {
  return {
    ...memory,
    sessionMeta: {
      ...memory.sessionMeta,
      serverVersion: result.version,
      serverUpdatedAt: result.updatedAt
    }
  };
}

type PendingSync = {
  sessionId: string;
  memory: WorkspaceMemory;
  projectId?: string | null;
  workspaceKey?: string | null;
};

let syncTimer: ReturnType<typeof setTimeout> | null = null;
let pendingSync: PendingSync | null = null;
let syncInFlight = false;
let onSyncSuccess: ((sessionId: string, memory: WorkspaceMemory) => void) | null = null;

export function setSessionSyncSuccessHandler(
  handler: ((sessionId: string, memory: WorkspaceMemory) => void) | null
): void {
  onSyncSuccess = handler;
}

async function flushPendingSessionSync(): Promise<void> {
  if (syncInFlight || !pendingSync) {
    return;
  }
  const job = pendingSync;
  pendingSync = null;
  syncInFlight = true;
  try {
    const result = await pushServerSession(job.sessionId, job.memory, {
      projectId: job.projectId,
      workspaceKey: job.workspaceKey,
      expectedVersion: job.memory.sessionMeta.serverVersion ?? undefined
    });
    if (result) {
      const updated = applyServerSyncMeta(job.memory, result);
      onSyncSuccess?.(job.sessionId, updated);
      if (pendingSync?.sessionId === job.sessionId) {
        pendingSync.memory = updated;
      }
    }
  } catch (e) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn("[sessionMemorySync] push failed", e);
    }
  } finally {
    syncInFlight = false;
    if (pendingSync) {
      void flushPendingSessionSync();
    }
  }
}

export function debouncedSyncWorkspaceMemoryToServer(
  sessionId: string,
  memory: WorkspaceMemory,
  opts?: { projectId?: string | null; workspaceKey?: string | null }
): void {
  pendingSync = {
    sessionId,
    memory,
    projectId: opts?.projectId,
    workspaceKey: opts?.workspaceKey
  };
  if (syncTimer) {
    clearTimeout(syncTimer);
  }
  syncTimer = setTimeout(() => {
    syncTimer = null;
    void flushPendingSessionSync();
  }, SYNC_DEBOUNCE_MS);
}

export async function flushDebouncedSessionMemorySync(): Promise<void> {
  if (syncTimer) {
    clearTimeout(syncTimer);
    syncTimer = null;
  }
  await flushPendingSessionSync();
}

export async function hydrateWorkspaceMemoryFromServer(
  local: WorkspaceMemory
): Promise<WorkspaceMemory> {
  const sessionId = local.sessionMeta.sessionId;
  const remote = await fetchServerSession(sessionId);
  if (!remote) {
    return local;
  }
  const merged = mergeWorkspaceMemory(local, remote.memory, remote.updatedAt);
  return applyServerSyncMeta(merged, {
    version: remote.version,
    updatedAt: remote.updatedAt
  });
}
