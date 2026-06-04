import { describe, expect, it } from "vitest";

import { parseApiErrorMessage } from "./llm";

describe("parseApiErrorMessage", () => {
  it("returns string detail as-is", () => {
    const txt = JSON.stringify({ detail: "OpenRouter error [401]" });
    expect(parseApiErrorMessage(502, txt)).toBe("OpenRouter error [401]");
  });

  it("returns detail.reason for object detail", () => {
    const txt = JSON.stringify({
      detail: { kind: "error", reason: "plan_validation_failed: bad plan" }
    });
    expect(parseApiErrorMessage(422, txt)).toBe(
      "[422] plan_validation_failed: bad plan"
    );
  });

  it("falls back to status-prefixed raw text", () => {
    expect(parseApiErrorMessage(500, "internal error")).toBe("[500] internal error");
  });
});
