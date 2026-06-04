import { afterEach, describe, expect, it, vi } from "vitest";

import { combinedAbortSignalForFetch } from "./llm";

describe("combinedAbortSignalForFetch", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("aborts merged signal when user signal aborts", () => {
    const user = new AbortController();
    const { signal, armTimeout, disarm } = combinedAbortSignalForFetch(
      60_000,
      user.signal
    );
    armTimeout();
    user.abort();
    expect(signal.aborted).toBe(true);
    disarm();
  });

  it("aborts after deadline when no user signal", async () => {
    vi.useFakeTimers();
    const { signal, armTimeout, disarm } = combinedAbortSignalForFetch(1000);
    armTimeout();
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(signal.aborted).toBe(true);
    disarm();
  });
});
