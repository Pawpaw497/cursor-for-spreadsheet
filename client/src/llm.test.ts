import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildAgentProjectPlanRequestBody,
  resolveTableRefs,
  type AgentProjectPlanRequestOpts
} from "./llm";
import type { TableData } from "./types";

const sampleTable: TableData = {
  name: "Sheet1",
  schema: [{ key: "a", type: "string" }],
  rows: [{ a: "one" }, { a: "two" }]
};

describe("resolveTableRefs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns empty mapping without fetch when tables is empty", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const refs = await resolveTableRefs([]);

    expect(refs).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uploads tables and returns name to tableId mapping", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ tableId: "tid-1", rowCount: 2 })
    });
    vi.stubGlobal("fetch", fetchMock);

    const refs = await resolveTableRefs([sampleTable]);

    expect(refs).toEqual({ Sheet1: "tid-1" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Client-Request-Id")).toMatch(/^[a-f0-9]{64}$/);
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({
      name: "Sheet1",
      schema: sampleTable.schema,
      rows: sampleTable.rows
    });
  });

  it("throws readable error when upload fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 413,
        text: async () => "payload too large"
      })
    );

    await expect(resolveTableRefs([sampleTable])).rejects.toThrow(/payload too large|413/i);
  });
});

describe("buildAgentProjectPlanRequestBody", () => {
  const baseOpts: AgentProjectPlanRequestOpts = {
    prompt: "add column",
    tables: [sampleTable]
  };

  it("emits tableRef and omits sampleRows when given tableRefs mapping", () => {
    const body = buildAgentProjectPlanRequestBody(baseOpts, { Sheet1: "t1" });

    expect(body.tables).toEqual([
      {
        name: "Sheet1",
        schema: sampleTable.schema,
        tableRef: "t1"
      }
    ]);
    const tables = body.tables as Record<string, unknown>[];
    expect(tables[0]).not.toHaveProperty("sampleRows");
  });
});
