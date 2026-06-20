import { describe, expect, it } from "vitest";

import { oracleTrustSpec } from "./findingBadges";

describe("oracleTrustSpec", () => {
  // The trust signal per failing assertion (design-direction semantic colours):
  // rule-derived → emerald (pass), spec-grounded → blue (info),
  // characterization → amber (flaky). Colour level + the source word.
  it("maps rule-derived to the emerald (pass) trust level", () => {
    expect(oracleTrustSpec("rule-derived")).toEqual({
      level: "pass",
      label: "Rule-derived",
    });
  });

  it("maps spec-grounded to the blue (info) trust level", () => {
    expect(oracleTrustSpec("spec-grounded")).toEqual({
      level: "info",
      label: "Spec-grounded",
    });
  });

  it("maps characterization to the amber (flaky) trust level", () => {
    expect(oracleTrustSpec("characterization")).toEqual({
      level: "flaky",
      label: "Characterization",
    });
  });

  it("falls back to a neutral badge for an unknown source", () => {
    expect(oracleTrustSpec("mystery")).toEqual({ level: "neutral", label: "mystery" });
  });
});
