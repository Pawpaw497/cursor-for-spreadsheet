import { afterEach, describe, expect, it, vi } from "vitest";

import {
  mapAgentStreamEventsToResult,
  requestAgentProjectPlanViaStream
} from "./agentProjectPlan";
import type { AgentStreamEvent } from "./agentStream";

function sseReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    }
  });
}

describe("mapAgentStreamEventsToResult", () => {
  it("maps clarification terminal event", () => {
    const events: AgentStreamEvent[] = [
      {
        kind: "clarification",
        data: {
          question: "Which table?",
          options: ["Sheet1", "Sheet2"],
          context: "Ambiguous add_column"
        }
      }
    ];
    const result = mapAgentStreamEventsToResult(events);
    expect(result.kind).toBe("clarification");
    if (result.kind === "clarification") {
      expect(result.clarification.question).toBe("Which table?");
      expect(result.clarification.options).toEqual(["Sheet1", "Sheet2"]);
      expect(result.clarification.context).toBe("Ambiguous add_column");
    }
  });

  it("prefers preview_ready over plan_done", () => {
    const plan = {
      intent: "t",
      steps: [{ action: "add_column", name: "c", expression: "1" }]
    };
    const events: AgentStreamEvent[] = [
      {
        kind: "preview_ready",
        data: {
          plan,
          preview: {
            id: "pv1",
            plan,
            diff: {
              addedColumns: ["c"],
              modifiedColumns: [],
              validationWarnings: [],
              validationErrors: []
            },
            newTables: [],
            status: "pending",
            created_at: 1
          },
          state: { revision_count: 0 }
        }
      },
      { kind: "plan_done", data: { plan, state: {} } }
    ];
    const result = mapAgentStreamEventsToResult(events);
    expect(result.kind).toBe("preview_ready");
  });

  it("maps plan_done to plan result", () => {
    const plan = {
      intent: "t",
      steps: [{ action: "add_column", name: "c", expression: "1" }]
    };
    const result = mapAgentStreamEventsToResult([{ kind: "plan_done", data: { plan } }]);
    expect(result.kind).toBe("plan");
    if (result.kind === "plan") {
      expect(result.plan.steps).toHaveLength(1);
    }
  });

  it("throws on finish without plan", () => {
    expect(() =>
      mapAgentStreamEventsToResult([{ kind: "finish", data: { reason: "max_turns" } }])
    ).toThrow(/agent-stream finish: max_turns/);
  });
});

describe("requestAgentProjectPlanViaStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("consumes SSE clarification and maps to result kind", async () => {
    const sse =
      'event: clarification\ndata: {"question":"Which?","options":["A"],"context":"ctx"}\n\n';
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: sseReadableStream([sse])
      })
    );

    const result = await requestAgentProjectPlanViaStream({
      prompt: "add column",
      tables: []
    });

    expect(result.kind).toBe("clarification");
    if (result.kind === "clarification") {
      expect(result.clarification.question).toBe("Which?");
      expect(result.clarification.options).toEqual(["A"]);
    }
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8787/api/agent-stream",
      expect.objectContaining({ method: "POST" })
    );
  });
});
