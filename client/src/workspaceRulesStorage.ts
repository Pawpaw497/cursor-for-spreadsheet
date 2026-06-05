const RULES_STORAGE_KEY_PREFIX = "spreadsheet-cursor:rules:";

function storageKey(workspaceKey: string): string {
  return `${RULES_STORAGE_KEY_PREFIX}${workspaceKey}`;
}

export function loadWorkspaceRules(workspaceKey: string | null | undefined): string {
  if (typeof localStorage === "undefined" || !workspaceKey) {
    return "";
  }
  return localStorage.getItem(storageKey(workspaceKey)) ?? "";
}

export function saveWorkspaceRules(workspaceKey: string, rules: string): void {
  if (typeof localStorage === "undefined" || !workspaceKey) {
    return;
  }
  try {
    localStorage.setItem(storageKey(workspaceKey), rules);
  } catch {
    // ignore quota errors
  }
}
