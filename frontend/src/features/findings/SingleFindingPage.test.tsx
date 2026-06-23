import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  findingApi: { listOpen: vi.fn() },
  runApi: { findings: vi.fn() },
}));

import { findingApi, runApi } from "@/lib/api/client";
import type { Finding } from "@/lib/api/types";

import { SingleFindingPage } from "./SingleFindingPage";

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f1",
    project_id: "p1",
    run_id: "run1",
    root_cause_key: "endpoint=POST api/orders#fail|status=401",
    title: "Orders accepted without authentication",
    layer: "api",
    severity: "critical",
    status: "flaky",
    oracle_source: "rule-derived",
    explains_count: 3,
    expected: { status: 200, assertions: [{ kind: "status" }] },
    location: {
      anchor: {
        node_type: "endpoint",
        identifier: "POST api/orders",
        label: "POST api/orders",
      },
      page: "/checkout",
      endpoints: ["POST api/orders"],
      tables: ["orders"],
    },
    evidence: [{ summary: "Expected 401, got 200", oracle_source: "rule-derived" }],
    history: {
      classification: "flaky",
      occurrence_count: 4,
      first_seen_run: "run-001",
      last_seen_run: "run-009",
    },
    triage: { status: "acknowledged" },
    ...over,
  };
}

function inboxOf(items: Finding[]) {
  return {
    ok: true,
    status: 200,
    data: { items, total: items.length, limit: 100, offset: 0 },
  };
}

function runFindingsOf(findings: Finding[]) {
  return {
    ok: true,
    status: 200,
    data: { run_id: "run1", count: findings.length, findings },
  };
}

describe("SingleFindingPage", () => {
  beforeEach(() => {
    vi.mocked(findingApi.listOpen).mockReset();
    vi.mocked(runApi.findings).mockReset();
    // No `?run=` by default — the page falls back to the open-inbox scan.
    window.history.pushState({}, "", "/findings/f1");
  });

  it("renders the finding as a structured bug report from real data", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(inboxOf([finding({})]));

    render(<SingleFindingPage findingId="f1" />);

    expect(
      await screen.findByRole("heading", {
        name: "Orders accepted without authentication",
      }),
    ).toBeInTheDocument();
    // What's wrong (the failure line parsed from the root cause key).
    expect(screen.getByText(/POST api\/orders returned 401/)).toBeInTheDocument();
    // Blast path hop + layer + the trust mark (our differentiator). The trust
    // mark renders both for the finding and per-evidence, so allow multiple.
    expect(screen.getAllByText("POST api/orders").length).toBeGreaterThan(0);
    expect(screen.getAllByText("rule-derived").length).toBeGreaterThan(0);
    // Evidence assertion line.
    expect(screen.getByText("Expected 401, got 200")).toBeInTheDocument();
    // Developer detail carries the raw root cause key.
    expect(
      screen.getByText("endpoint=POST api/orders#fail|status=401"),
    ).toBeInTheDocument();
  });

  it("shows Severity and Status as separate, distinct axes", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      inboxOf([finding({ severity: "critical", triage: { status: "acknowledged" } })]),
    );

    render(<SingleFindingPage findingId="f1" />);
    await screen.findByRole("heading", {
      name: "Orders accepted without authentication",
    });

    // Severity = technical impact; Status = triage disposition. Both labelled,
    // shown separately, with different values.
    expect(screen.getByText("Severity")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Acknowledged")).toBeInTheDocument();
  });

  it("is honest about fields the payload doesn't carry", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(inboxOf([finding({})]));

    render(<SingleFindingPage findingId="f1" />);
    await screen.findByRole("heading", {
      name: "Orders accepted without authentication",
    });

    // Steps-to-reproduce and screenshot aren't on the payload — placeholdered, not faked.
    expect(screen.getByText(/Reproduction steps aren.t captured/)).toBeInTheDocument();
    expect(screen.getByText(/Screenshot capture isn.t available/)).toBeInTheDocument();
  });

  it("reports the reproduction count for a flaky finding without a fake denominator", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      inboxOf([
        finding({
          status: "flaky",
          history: { classification: "flaky", occurrence_count: 4 },
        }),
      ]),
    );

    render(<SingleFindingPage findingId="f1" />);
    await screen.findByRole("heading", {
      name: "Orders accepted without authentication",
    });

    expect(screen.getByText(/Failed in 4 runs of recent history/)).toBeInTheDocument();
  });

  it("loads run-scoped findings when ?run= is present (covers any disposition)", async () => {
    window.history.pushState({}, "", "/findings/f1?run=run1");
    vi.mocked(runApi.findings).mockResolvedValue(runFindingsOf([finding({})]));

    render(<SingleFindingPage findingId="f1" />);

    expect(
      await screen.findByRole("heading", {
        name: "Orders accepted without authentication",
      }),
    ).toBeInTheDocument();
    expect(runApi.findings).toHaveBeenCalledWith("run1");
    expect(findingApi.listOpen).not.toHaveBeenCalled();
  });

  it("shows an honest not-available state when the id isn't in the reachable set", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(inboxOf([]));

    render(<SingleFindingPage findingId="missing" />);

    expect(
      await screen.findByText("This finding isn't available here"),
    ).toBeInTheDocument();
  });
});
