import type { GridApi } from "ag-grid-community";

export type SelectedRange = {
  startRow: number;
  endRow: number;
  colIds?: string[];
};

export type AgentRequestContext = {
  activeTable?: string;
  selectedRange?: SelectedRange;
  focusedColumn?: string;
  workspaceRules?: string;
};

/** Build optional `@`-style context from grid focus/selection for Agent requests. */
export function buildAgentRequestContext(
  activeTable: string,
  gridApi: GridApi | null | undefined,
  workspaceRules: string
): AgentRequestContext | undefined {
  const context: AgentRequestContext = { activeTable };
  let hasExtra = true;

  const rules = workspaceRules.trim();
  if (rules) {
    context.workspaceRules = rules;
  }

  if (gridApi) {
    const nodes = gridApi.getSelectedNodes();
    if (nodes.length > 0) {
      const indices = nodes
        .map((n) => n.rowIndex)
        .filter((i): i is number => i != null);
      if (indices.length > 0) {
        context.selectedRange = {
          startRow: Math.min(...indices),
          endRow: Math.max(...indices)
        };
      }
    } else {
      const focused = gridApi.getFocusedCell();
      const colId = focused?.column?.getColId();
      if (colId && colId !== "__rowNum") {
        context.focusedColumn = colId;
      }
    }
  }

  if (!rules && !context.selectedRange && !context.focusedColumn) {
    hasExtra = false;
  }

  return hasExtra || activeTable ? context : undefined;
}
