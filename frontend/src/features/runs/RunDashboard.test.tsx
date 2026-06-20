import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  runApi: { get: vi.fn(), findings: vi.fn(), triage: vi.fn() },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { runApi } from "@/lib/api/client";
import type { Finding, JobStatusValue } from "@/lib/api/types";

import { RunDashboard } from "./RunDashboard";

function summaryResult(summary: Record<string, unknown>) {
  const status: JobStatusValue = "succeeded";
  return {
    ok: true,
    status: 200,
    data: { run_id: "r1", mode: "mode_b", status, summary },
  };
}

function findingsResult(findings: Finding[]) {
  return {
    ok: true,
    status: 200,
    data: { run_id: "r1", count: findings.length, findings },
  };
}

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f1",
    root_cause_key: "k",
    title: "A finding",
    layer: "api",
    severity: "major",
    status: "new",
    oracle_source: "rule-derived",
    explains_count: 1,
    ...over,
  };
}

describe("RunDashboard", () => {
  beforeEach(() => {
    vi.mocked(runApi.get).mockReset();
    vi.mocked(runApi.findings).mockReset();
  });

  it("renders the summary stat cards from the run summary", async () => {
    vi.mocked(runApi.get).mockResolvedValue(
      summaryResult({ pass_rate: 0.8, failed: 2, errors: 3, coverage: 0.6 }),
    );
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([finding({ id: "f1", oracle_source: "rule-derived" })]),
    );

    render(<RunDashboard runId="r1" />);

    expect(await screen.findByText("80%")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("Pass rate")).toBeInTheDocument();
    expect(screen.getByText("Coverage")).toBeInTheDocument();
  });

  it("renders the ranked findings with correct badges, in order", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({}));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({
          id: "a",
          title: "Checkout 500",
          severity: "critical",
          layer: "api",
          oracle_source: "rule-derived",
          status: "regression",
          explains_count: 3,
        }),
        finding({
          id: "b",
          title: "Cart count drifted",
          severity: "minor",
          layer: "ui",
          oracle_source: "characterization",
          status: "new",
          explains_count: 1,
        }),
      ]),
    );

    render(<RunDashboard runId="r1" />);

    const rowA = (await screen.findByText("Checkout 500")).closest("button")!;
    expect(within(rowA).getByText("Critical")).toBeInTheDocument();
    expect(within(rowA).getByText("api")).toBeInTheDocument();
    expect(within(rowA).getByText("Rule-derived")).toBeInTheDocument();
    expect(within(rowA).getByText("Regression")).toBeInTheDocument();
    expect(within(rowA).getByText(/explains 3 tests/)).toBeInTheDocument();

    const rowB = screen.getByText("Cart count drifted").closest("button")!;
    expect(within(rowB).getByText("Minor")).toBeInTheDocument();
    expect(within(rowB).getByText("ui")).toBeInTheDocument();
    expect(within(rowB).getByText("Behaviour-changed")).toBeInTheDocument();
    expect(within(rowB).getByText("New")).toBeInTheDocument();
    expect(within(rowB).getByText(/explains 1 test$/)).toBeInTheDocument();

    // Server ranking is preserved (A before B).
    const list = rowA.parentElement!;
    const rows = within(list).getAllByRole("button");
    expect(rows[0]).toHaveTextContent("Checkout 500");
    expect(rows[1]).toHaveTextContent("Cart count drifted");
  });

  it("narrows the list when a filter is applied", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({}));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({ id: "a", title: "Checkout 500", severity: "critical" }),
        finding({ id: "b", title: "Cart count drifted", severity: "minor" }),
      ]),
    );

    render(<RunDashboard runId="r1" />);
    await screen.findByText("Checkout 500");

    fireEvent.change(screen.getByLabelText("Severity"), {
      target: { value: "critical" },
    });

    expect(screen.getByText("Checkout 500")).toBeInTheDocument();
    expect(screen.queryByText("Cart count drifted")).toBeNull();
  });

  it("renders the loading state while fetching", () => {
    vi.mocked(runApi.get).mockReturnValue(new Promise(() => {}));
    vi.mocked(runApi.findings).mockReturnValue(new Promise(() => {}));

    render(<RunDashboard runId="r1" />);

    expect(screen.getByText("Loading run…")).toBeInTheDocument();
  });

  it("renders the empty state when there are no findings", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({ pass_rate: 1 }));
    vi.mocked(runApi.findings).mockResolvedValue(findingsResult([]));

    render(<RunDashboard runId="r1" />);

    expect(await screen.findByText("No findings")).toBeInTheDocument();
    expect(
      screen.getByText("Every test passed in this run — nothing to triage."),
    ).toBeInTheDocument();
  });

  it("renders the error state when the run cannot be loaded", async () => {
    vi.mocked(runApi.get).mockResolvedValue({
      ok: false,
      status: 404,
      data: null,
      error: "Run not found.",
    });
    vi.mocked(runApi.findings).mockResolvedValue(findingsResult([]));

    render(<RunDashboard runId="r1" />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Run not found."),
    );
  });

  it("badges the triage disposition and de-emphasizes muted findings", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({}));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({
          id: "ack",
          title: "Acknowledged issue",
          triage: { status: "acknowledged" },
        }),
        finding({
          id: "muted",
          title: "Muted issue",
          triage: { status: "wont_fix" },
        }),
      ]),
    );

    render(<RunDashboard runId="r1" />);

    const ackRow = (await screen.findByText("Acknowledged issue")).closest("button")!;
    expect(within(ackRow).getByText("Acknowledged")).toBeInTheDocument();
    expect(ackRow).not.toHaveClass("opacity-60");

    const mutedRow = screen.getByText("Muted issue").closest("button")!;
    expect(within(mutedRow).getByText("Won't fix")).toBeInTheDocument();
    expect(mutedRow).toHaveClass("opacity-60"); // muted → de-emphasized
  });

  it("hides muted findings when the 'hide muted' toggle is on", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({}));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({ id: "open", title: "Open issue" }),
        finding({ id: "muted", title: "Muted issue", triage: { status: "wont_fix" } }),
      ]),
    );

    render(<RunDashboard runId="r1" />);
    await screen.findByText("Open issue");
    expect(screen.getByText("Muted issue")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Hide muted"));

    expect(screen.getByText("Open issue")).toBeInTheDocument();
    expect(screen.queryByText("Muted issue")).toBeNull();
  });
});
