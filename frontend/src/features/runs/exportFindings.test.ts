import { describe, expect, it } from "vitest";

import type { Finding } from "@/lib/api/types";

import { findingsToCsv } from "./exportFindings";

const BASE: Finding = {
  id: "f1",
  root_cause_key: "key",
  title: "Checkout 500",
  layer: "api",
  severity: "critical",
  status: "new",
  oracle_source: "rule-derived",
  explains_count: 3,
};

describe("findingsToCsv", () => {
  it("always includes the header row, even with no findings", () => {
    expect(findingsToCsv([])).toBe(
      "id,title,layer,severity,status,oracle_source,explains_count,history_classification,triage_status",
    );
  });

  it("renders a full row for a finding with no optional fields", () => {
    const csv = findingsToCsv([BASE]);
    const rows = csv.split("\n");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toBe("f1,Checkout 500,api,critical,new,rule-derived,3,,");
  });

  it("includes history classification and triage status when present", () => {
    const finding: Finding = {
      ...BASE,
      history: { classification: "regression", occurrence_count: 2 },
      triage: { status: "acknowledged" },
    };
    const rows = findingsToCsv([finding]).split("\n");
    expect(rows[1]).toBe(
      "f1,Checkout 500,api,critical,new,rule-derived,3,regression,acknowledged",
    );
  });

  it("quotes a title containing a comma, doubling any internal quotes", () => {
    const finding: Finding = { ...BASE, title: 'Checkout "500" error, retried' };
    const rows = findingsToCsv([finding]).split("\n");
    expect(rows[1]).toBe(
      'f1,"Checkout ""500"" error, retried",api,critical,new,rule-derived,3,,',
    );
  });

  it("quotes a title containing a newline", () => {
    const finding: Finding = { ...BASE, title: "Line one\nLine two" };
    expect(findingsToCsv([finding])).toContain('"Line one\nLine two"');
  });

  it("renders one row per finding, in the given order", () => {
    const second: Finding = { ...BASE, id: "f2", title: "Second issue" };
    const rows = findingsToCsv([BASE, second]).split("\n");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toContain("f1,");
    expect(rows[2]).toContain("f2,");
  });
});
