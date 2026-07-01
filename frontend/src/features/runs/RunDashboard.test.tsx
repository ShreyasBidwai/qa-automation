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
    data: { run_id: "r1", project_id: "p1", mode: "mode_b", status, summary },
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

// The list (master) and the detail panel both render finding titles, so queries
// are scoped to a region to keep them unambiguous.
const stats = () => screen.getByRole("region", { name: "Run stats" });
const listRegion = () => screen.findByRole("region", { name: "Findings" });

describe("RunDashboard", () => {
  beforeEach(() => {
    vi.mocked(runApi.get).mockReset();
    vi.mocked(runApi.findings).mockReset();
  });

  it("renders the four headline stat cards from the run + findings", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({ pass_rate: 0.8 }));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({ id: "f1", severity: "major", oracle_source: "rule-derived" }),
      ]),
    );

    render(<RunDashboard runId="r1" />);

    expect(await screen.findByText("80%")).toBeInTheDocument();
    const cards = stats();
    expect(within(cards).getByText("Pass rate")).toBeInTheDocument();
    expect(within(cards).getByText("Findings")).toBeInTheDocument();
    expect(within(cards).getByText("New / Regressions")).toBeInTheDocument();
    expect(within(cards).getByText("Confidence")).toBeInTheDocument();
    // Stats are derived from the findings list, not invented.
    expect(within(cards).getByText("1 major")).toBeInTheDocument();
    expect(within(cards).getByText("All rule-derived")).toBeInTheDocument();
  });

  it("renders the ranked findings with trust marks + badges, in order", async () => {
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

    const list = await listRegion();
    const rowA = within(list).getByText("Checkout 500").closest("button")!;
    expect(within(rowA).getByText("Critical")).toBeInTheDocument();
    expect(within(rowA).getByText("api")).toBeInTheDocument();
    expect(within(rowA).getByText("rule-derived")).toBeInTheDocument();
    expect(within(rowA).getByText("Regression")).toBeInTheDocument();

    const rowB = within(list).getByText("Cart count drifted").closest("button")!;
    expect(within(rowB).getByText("Minor")).toBeInTheDocument();
    expect(within(rowB).getByText("ui")).toBeInTheDocument();
    expect(within(rowB).getByText("characterization")).toBeInTheDocument();
    expect(within(rowB).getByText("New")).toBeInTheDocument();

    // Server ranking is preserved (A before B).
    const rows = within(list).getAllByRole("button");
    expect(rows[0]).toHaveTextContent("Checkout 500");
    expect(rows[1]).toHaveTextContent("Cart count drifted");
  });

  it("opens the first finding in the detail panel by default", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({}));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({ id: "a", title: "Checkout 500", severity: "critical" }),
        finding({ id: "b", title: "Cart count drifted", severity: "minor" }),
      ]),
    );

    render(<RunDashboard runId="r1" />);

    const detail = await screen.findByRole("region", { name: "Finding detail" });
    // The first finding's detail (its title + the field grid) is shown without a click.
    expect(
      within(detail).getByRole("heading", { name: "Checkout 500" }),
    ).toBeInTheDocument();
    expect(within(detail).getByText("Blast path")).toBeInTheDocument();
  });

  it("updates the detail panel when another finding is selected", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({}));
    vi.mocked(runApi.findings).mockResolvedValue(
      findingsResult([
        finding({ id: "a", title: "Checkout 500", severity: "critical" }),
        finding({ id: "b", title: "Cart count drifted", severity: "minor" }),
      ]),
    );

    render(<RunDashboard runId="r1" />);

    const list = await listRegion();
    fireEvent.click(within(list).getByText("Cart count drifted").closest("button")!);

    const detail = screen.getByRole("region", { name: "Finding detail" });
    expect(
      within(detail).getByRole("heading", { name: "Cart count drifted" }),
    ).toBeInTheDocument();
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
    const list = await listRegion();

    fireEvent.change(within(list).getByLabelText("Severity"), {
      target: { value: "critical" },
    });

    expect(within(list).getByText("Checkout 500")).toBeInTheDocument();
    expect(within(list).queryByText("Cart count drifted")).toBeNull();
  });

  it("renders the loading state while fetching", () => {
    vi.mocked(runApi.get).mockReturnValue(new Promise(() => {}));
    vi.mocked(runApi.findings).mockReturnValue(new Promise(() => {}));

    render(<RunDashboard runId="r1" />);

    expect(screen.getByText("Loading run…")).toBeInTheDocument();
  });

  it("renders the clean-run state when there are no findings", async () => {
    vi.mocked(runApi.get).mockResolvedValue(summaryResult({ pass_rate: 1 }));
    vi.mocked(runApi.findings).mockResolvedValue(findingsResult([]));

    render(<RunDashboard runId="r1" />);

    expect(await screen.findByText("This run came back clean")).toBeInTheDocument();
    expect(screen.getByText(/No findings across the run/)).toBeInTheDocument();
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
      expect(screen.getByText("Couldn't load this run")).toBeInTheDocument(),
    );
    expect(screen.getByText("Run not found.")).toBeInTheDocument();
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

    const list = await listRegion();
    const ackRow = within(list).getByText("Acknowledged issue").closest("button")!;
    expect(within(ackRow).getByText("Acknowledged")).toBeInTheDocument();
    expect(ackRow).not.toHaveClass("opacity-60");

    const mutedRow = within(list).getByText("Muted issue").closest("button")!;
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
    const list = await listRegion();
    expect(within(list).getByText("Muted issue")).toBeInTheDocument();

    fireEvent.click(within(list).getByLabelText("Hide muted"));

    expect(within(list).getByText("Open issue")).toBeInTheDocument();
    expect(within(list).queryByText("Muted issue")).toBeNull();
  });
});
