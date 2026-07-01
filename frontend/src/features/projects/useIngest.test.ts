import { describe, expect, it } from "vitest";

import { ingestFailureMessage } from "./useIngest";

describe("ingestFailureMessage", () => {
  // A failed build must read as "here's what to fix", never a scary internal error.
  it("maps a repo-access failure to an actionable message", () => {
    const msg = ingestFailureMessage("GitCheckoutError");
    expect(msg).toMatch(/repository/i);
    expect(msg).toMatch(/token|read permission/i);
    expect(msg).not.toMatch(/our end|notified/i);
  });

  it("maps a config error to a config-oriented message", () => {
    expect(ingestFailureMessage("ApiConfigError")).toMatch(/repo url|stack/i);
  });

  it("names an unknown reason instead of hiding it", () => {
    expect(ingestFailureMessage("SomethingWeird")).toContain("SomethingWeird");
  });

  it("has a sensible fallback when there's no detail", () => {
    expect(ingestFailureMessage(null)).toMatch(/failed/i);
    expect(ingestFailureMessage(undefined)).toMatch(/failed/i);
  });
});
