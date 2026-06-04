import { describe, expect, it } from "vitest";

import { getLlmClientTimeoutMs } from "./llm";

describe("getLlmClientTimeoutMs", () => {
  it("uses fallback aligned with server default upstream max + 30s buffer (150s)", () => {
    expect(getLlmClientTimeoutMs()).toBe(150_000);
  });
});
