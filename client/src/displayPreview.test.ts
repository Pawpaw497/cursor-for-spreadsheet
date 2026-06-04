import { describe, expect, it } from "vitest";

import { applyProjectPlan } from "./engine";
import type { Plan, TableData } from "./types";

function table(name: string, rows: Record<string, unknown>[]): TableData {
  return {
    name,
    rows,
    schema: Object.keys(rows[0] ?? {}).map((key) => ({ key, type: "string" as const }))
  };
}

describe("applyProjectPlan preview display", () => {
  it("preview rows differ from baseline after add_column", () => {
    const tables = {
      Sheet1: table("Sheet1", [{ price: 10, qty: 2 }])
    };
    const plan: Plan = {
      intent: "add total",
      steps: [
        {
          action: "add_column",
          name: "total",
          expression: "row.price * row.qty",
          table: "Sheet1"
        }
      ]
    };

    const preview = applyProjectPlan(tables, plan);
    expect(preview.tables.Sheet1!.rows[0]!.total).toBe(20);
    expect(tables.Sheet1.rows[0]!.total).toBeUndefined();
    expect(preview.diff.addedColumns).toContain("total");
  });

  it("includes new table names in preview tables", () => {
    const tables = {
      Left: table("Left", [{ id: 1, name: "a" }]),
      Right: table("Right", [{ id: 1, score: 9 }])
    };
    const plan: Plan = {
      intent: "join",
      steps: [
        {
          action: "join_tables",
          left: "Left",
          right: "Right",
          leftKey: "id",
          rightKey: "id",
          resultTable: "Joined"
        }
      ]
    };

    const preview = applyProjectPlan(tables, plan);
    expect(preview.newTables).toContain("Joined");
    expect(preview.tables.Joined).toBeDefined();
    expect(preview.tables.Joined!.rows.length).toBeGreaterThan(0);
    expect(tables.Joined).toBeUndefined();
  });
});
