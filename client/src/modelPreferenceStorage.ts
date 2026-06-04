import type { ConfigResponse, ModelSource } from "./llm";

export const MODEL_PREF_STORAGE_KEY = "spreadsheet-cursor:model-pref";

const STORAGE_VERSION = 1;

export type ModelPreference = {
  modelSource: ModelSource;
  cloudModelId: string;
  localModelId: string;
};

type StoredModelPreferencePayload = {
  version: number;
  modelSource: ModelSource;
  cloudModelId: string;
  localModelId: string;
};

function isValidModelSource(value: unknown): value is ModelSource {
  return value === "cloud" || value === "local";
}

function pickCloudModelId(config: ConfigResponse, preferred?: string): string {
  const models = config.openRouterModels;
  if (models.length === 0) return "";
  if (preferred && models.some((m) => m.id === preferred)) return preferred;
  return config.openRouterModel || models[0]!.id;
}

function pickLocalModelId(config: ConfigResponse, preferred?: string): string {
  const models = config.ollamaModels;
  if (models.length === 0) return "";
  if (preferred && models.some((m) => m.id === preferred)) return preferred;
  return config.ollamaModel || models[0]!.id;
}

export function resolveModelPreference(
  saved: ModelPreference | null,
  config: ConfigResponse
): ModelPreference {
  const modelSource =
    saved && isValidModelSource(saved.modelSource) ? saved.modelSource : "cloud";

  return {
    modelSource,
    cloudModelId: pickCloudModelId(config, saved?.cloudModelId),
    localModelId: pickLocalModelId(config, saved?.localModelId),
  };
}

export function loadModelPreference(): ModelPreference | null {
  if (typeof localStorage === "undefined") {
    return null;
  }
  try {
    const raw = localStorage.getItem(MODEL_PREF_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    const record = parsed as Record<string, unknown>;
    if (record.version !== STORAGE_VERSION) return null;
    if (!isValidModelSource(record.modelSource)) return null;
    if (typeof record.cloudModelId !== "string" || typeof record.localModelId !== "string") {
      return null;
    }
    return {
      modelSource: record.modelSource,
      cloudModelId: record.cloudModelId,
      localModelId: record.localModelId,
    };
  } catch {
    return null;
  }
}

export function saveModelPreference(pref: ModelPreference): void {
  if (typeof localStorage === "undefined") {
    return;
  }
  try {
    const body: StoredModelPreferencePayload = {
      version: STORAGE_VERSION,
      modelSource: pref.modelSource,
      cloudModelId: pref.cloudModelId,
      localModelId: pref.localModelId,
    };
    localStorage.setItem(MODEL_PREF_STORAGE_KEY, JSON.stringify(body));
  } catch (e) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn("[modelPreference] save failed", e);
    }
  }
}
