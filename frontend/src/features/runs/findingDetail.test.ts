import { describe, expect, it } from "vitest";

import type { Finding } from "@/lib/api/types";

import {
  buildRibbon,
  confidenceRationale,
  failureLine,
  parseRootCauseKey,
  parseSignature,
  statusMeaning,
} from "./findingDetail";

function finding(over: Partial<Finding>): Finding {
  return {
    id: "x",
    title: "t",
    root_cause_key: "endpoint=e#fail",
    layer: "api",
    severity: "major",
    status: "new",
    oracle_source: "rule-derived",
    explains_count: 1,
    ...over,
  };
}

describe("findingDetail", () => {
  it("parses the anchor and failure signature from a key", () => {
    const parsed = parseRootCauseKey(
      "table=orders,users#fail|status=500|assert=body,status",
    );
    expect(parsed.anchorKind).toBe("table");
    expect(parsed.anchorValue).toBe("orders,users");

    const sig = parseSignature(parsed.signature);
    expect(sig.outcome).toBe("fail");
    expect(sig.status).toBe("500");
    expect(sig.assertions).toEqual(["body", "status"]);
  });

  it("treats an unlocated key as having no cross-layer path", () => {
    expect(parseRootCauseKey("unlocated#error").anchorKind).toBe("none");
    expect(buildRibbon(finding({ root_cause_key: "unlocated#error" })).available).toBe(
      false,
    );
    expect(failureLine(finding({ root_cause_key: "unlocated#error" }))).toBeNull();
  });

  it("builds a full ribbon and highlights the anchored layer", () => {
    const ribbon = buildRibbon(
      finding({
        root_cause_key: "table=orders#fail",
        location: { page: "/p", endpoints: ["GET api/o"], tables: ["orders"] },
      }),
    );
    expect(ribbon.partial).toBe(false);
    expect(ribbon.hops.map((h) => h.tier)).toEqual(["UI", "API", "DB"]);
    expect(ribbon.hops.find((h) => h.tier === "DB")?.failing).toBe(true);
    expect(ribbon.hops.find((h) => h.tier === "API")?.failing).toBe(false);
  });

  it("explains confidence and status in plain language", () => {
    expect(confidenceRationale("characterization")).toMatch(/Behaviour-changed/);
    expect(statusMeaning("flaky")).toMatch(/oscillating/i);
  });
});
