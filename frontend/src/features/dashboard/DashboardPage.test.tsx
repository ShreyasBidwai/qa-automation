import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  accountApi: { dashboard: vi.fn() },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { accountApi } from "@/lib/api/client";
import type { AccountDashboard } from "@/lib/api/types";
import { navigate } from "@/lib/router";

import { DashboardPage } from "./DashboardPage";

function dashboard(over: Partial<AccountDashboard> = {}): AccountDashboard {
  return {
    range_days: 30,
    projects_total: 2,
    projects_by_status: { passing: 1, action_needed: 1 },
    open_findings: { critical: 1, major: 2, minor: 0, total: 3 },
    project_health: [
      {
        project_id: "p1",
        name: "Acme Billing",
        status: "action_needed",
        pass_rate: 0.62,
        open_findings: 3,
        last_run_at: "2026-02-01T00:00:00Z",
      },
      {
        project_id: "p2",
        name: "Orders API",
        status: "passing",
        pass_rate: 1,
        open_findings: 0,
        last_run_at: "2026-01-30T00:00:00Z",
      },
    ],
    runs_total: 9,
    tests_total: 120,
    outcomes: { pass: 90, fail: 6, error: 0, skipped: 24 },
    pass_rate: 0.9375,
    trend: [
      {
        date: "2026-01-30",
        runs: 4,
        passed: 40,
        failed: 4,
        errored: 0,
        skipped: 10,
        pass_rate: 0.9,
      },
      {
        date: "2026-01-31",
        runs: 5,
        passed: 50,
        failed: 2,
        errored: 0,
        skipped: 14,
        pass_rate: 0.96,
      },
    ],
    recent_runs: [
      {
        run_id: "r1",
        project_id: "p1",
        project_name: "Acme Billing",
        mode: "B",
        status: "failed",
        pass_rate: 0.62,
        created_at: "2026-02-01T00:00:00Z",
      },
    ],
    ...over,
  };
}

function ok(data: AccountDashboard) {
  return { ok: true, status: 200, data };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(accountApi.dashboard).mockReset();
    vi.mocked(navigate).mockReset();
  });

  it("renders the headline cards, project health, and recent runs", async () => {
    vi.mocked(accountApi.dashboard).mockResolvedValue(ok(dashboard()));

    render(<DashboardPage />);

    // Pass rate (verified) headline.
    expect(await screen.findByText("94%")).toBeInTheDocument();
    // The headline cards, incl. the open-findings breakdown (count + label split spans).
    const headline = screen.getByRole("region", { name: "Account headline" });
    expect(within(headline).getByText("Open findings")).toBeInTheDocument();
    expect(within(headline).getByText("major")).toBeInTheDocument();
    // Project health rows, worst-first (more open findings leads).
    const health = screen.getByText("Project health").closest("section")!;
    const names = within(health)
      .getAllByText(/^Acme Billing$|^Orders API$/)
      .map((n) => n.textContent);
    expect(names[0]).toBe("Acme Billing");
    // Recent runs feed.
    expect(screen.getByText("Recent runs")).toBeInTheDocument();
  });

  it("refetches when the time range changes", async () => {
    vi.mocked(accountApi.dashboard).mockResolvedValue(ok(dashboard()));

    render(<DashboardPage />);
    await screen.findByText("94%");
    expect(accountApi.dashboard).toHaveBeenLastCalledWith(30);

    fireEvent.click(screen.getByRole("radio", { name: "7D" }));
    await waitFor(() => expect(accountApi.dashboard).toHaveBeenLastCalledWith(7));
  });

  it("hands off to Projects when the account has no projects", async () => {
    vi.mocked(accountApi.dashboard).mockResolvedValue(
      ok(dashboard({ projects_total: 0, project_health: [], recent_runs: [] })),
    );

    render(<DashboardPage />);

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/projects"));
  });

  it("surfaces a load error honestly", async () => {
    vi.mocked(accountApi.dashboard).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "boom",
    });

    render(<DashboardPage />);

    expect(await screen.findByText("Couldn't load your dashboard")).toBeInTheDocument();
  });
});
