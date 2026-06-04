import { describe, expect, it } from "vitest";

import { parseAgentPreviewRecord } from "./llm";

describe("parseAgentPreviewRecord", () => {
  it("parses snake_case preview payloads from the API", () => {
    const raw = {
      id: "preview_abc",
      plan: {
        intent: "t",
        steps: [{ action: "add_column", name: "c", expression: "1" }]
      },
      diff: {
        addedColumns: ["c"],
        modifiedColumns: [],
        validationWarnings: [],
        validationErrors: []
      },
      new_tables: [],
      status: "pending",
      created_at: 1700000000
    };
    const rec = parseAgentPreviewRecord(raw as Record<string, unknown>);
    expect(rec.id).toBe("preview_abc");
    expect(rec.plan.steps).toHaveLength(1);
    expect(rec.diff.addedColumns).toContain("c");
    expect(rec.status).toBe("pending");
  });

  it("parses lookup_column and aggregate_table wire aliases (from, as)", () => {
    const raw = {
      id: "preview_multi",
      plan: {
        intent: "lookup and aggregate",
        steps: [
          {
            action: "lookup_column",
            mainTable: "销售订单",
            lookupTable: "产品信息",
            mainKey: "产品",
            lookupKey: "产品名称",
            columns: [
              { from: "类别", to: "类别" },
              { from: "成本价", to: "成本价" }
            ]
          },
          {
            action: "aggregate_table",
            source: "销售订单",
            groupBy: ["客户"],
            resultTable: "客户毛利汇总",
            aggregations: [
              { column: "金额", op: "sum", as: "总金额" },
              { column: "毛利", op: "sum", as: "总毛利" }
            ]
          }
        ]
      },
      diff: {
        addedColumns: [],
        modifiedColumns: [],
        validationWarnings: [],
        validationErrors: []
      },
      new_tables: ["客户毛利汇总"],
      status: "pending",
      created_at: 1700000000
    };
    const rec = parseAgentPreviewRecord(raw as Record<string, unknown>);
    expect(rec.plan.steps).toHaveLength(2);
    const lookup = rec.plan.steps[0];
    expect(lookup.action).toBe("lookup_column");
    if (lookup.action === "lookup_column") {
      expect(lookup.columns[0].from).toBe("类别");
    }
    const agg = rec.plan.steps[1];
    expect(agg.action).toBe("aggregate_table");
    if (agg.action === "aggregate_table") {
      expect(agg.aggregations[0].as).toBe("总金额");
    }
  });
});
