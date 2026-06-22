import { describe, expect, it } from "vitest";

import type { Finding } from "@/lib/api/types";

import {
  confidenceLabel,
  confidenceMix,
  historyCounts,
  severityCounts,
} from "./findingStats";

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f",
    root_cause_key: "k",
    title: "t",
    layer: "api",
    severity: "major",
    status: "new",
    oracle_source: "rule-derived",
    explains_count: 1,
    ...over,
  };
}

describe("severityCounts", () => {
  it("tallies findings by severity", () => {
    const counts = severityCounts([
      finding({ severity: "critical" }),
      finding({ severity: "critical" }),
      finding({ severity: "major" }),
      finding({ severity: "minor" }),
      finding({ severity: "unknown-sev" }),
    ]);
    expect(counts).toEqual({ critical: 2, major: 1, minor: 1 });
  });
});

describe("historyCounts", () => {
  it("counts new and regression findings by status", () => {
    const counts = historyCounts([
      finding({ status: "new" }),
      finding({ status: "regression" }),
      finding({ status: "known" }),
      finding({ status: "new" }),
    ]);
    expect(counts).toEqual({ new: 2, regression: 1 });
  });
});

describe("confidenceMix", () => {
  it("tallies oracle tiers and names the dominant one", () => {
    const mix = confidenceMix([
      finding({ oracle_source: "rule-derived" }),
      finding({ oracle_source: "rule-derived" }),
      finding({ oracle_source: "characterization" }),
      finding({ oracle_source: "spec-grounded" }),
    ]);
    expect(mix).toEqual({
      rule: 2,
      characterization: 1,
      spec: 1,
      dominant: "rule-derived",
    });
  });

  it("prefers the stronger tier on a tie", () => {
    const mix = confidenceMix([
      finding({ oracle_source: "rule-derived" }),
      finding({ oracle_source: "characterization" }),
    ]);
    expect(mix.dominant).toBe("rule-derived");
  });

  it("has no dominant tier for an empty list", () => {
    expect(confidenceMix([]).dominant).toBeNull();
  });
});

describe("confidenceLabel", () => {
  it("reads 'All …' when one tier covers every finding", () => {
    expect(
      confidenceLabel(confidenceMix([finding({ oracle_source: "rule-derived" })])),
    ).toBe("All rule-derived");
  });

  it("reads 'Mostly …' when one tier merely leads", () => {
    const mix = confidenceMix([
      finding({ oracle_source: "rule-derived" }),
      finding({ oracle_source: "rule-derived" }),
      finding({ oracle_source: "characterization" }),
    ]);
    expect(confidenceLabel(mix)).toBe("Mostly rule-derived");
  });

  it("reads '—' for an empty run", () => {
    expect(confidenceLabel(confidenceMix([]))).toBe("—");
  });
});
