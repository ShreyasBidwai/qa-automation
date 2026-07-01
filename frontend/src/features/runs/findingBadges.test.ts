import { describe, expect, it } from "vitest";

import { aiTriageSpec, oracleTrustSpec } from "./findingBadges";

describe("aiTriageSpec", () => {
  // The model's read: real bug pops (fail/red), flaky is amber, and the
  // not-the-app buckets go quiet; unknown/absent renders no chip.
  it("maps real-bug to the fail (red) level with an AI-prefixed label", () => {
    expect(aiTriageSpec("real-bug")).toEqual({ level: "fail", label: "AI: Real bug" });
  });

  it("maps flaky to the amber (flaky) level", () => {
    expect(aiTriageSpec("flaky")).toEqual({ level: "flaky", label: "AI: Flaky" });
  });

  it("keeps the not-the-app buckets quiet (neutral)", () => {
    expect(aiTriageSpec("bad-test")?.level).toBe("neutral");
    expect(aiTriageSpec("infra")?.level).toBe("neutral");
  });

  it("renders no chip for unknown / absent", () => {
    expect(aiTriageSpec("unknown")).toBeNull();
    expect(aiTriageSpec(null)).toBeNull();
    expect(aiTriageSpec(undefined)).toBeNull();
  });
});

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
