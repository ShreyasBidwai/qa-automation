import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  findingApi: { listOpen: vi.fn() },
  runApi: { triage: vi.fn() },
}));

import { findingApi } from "@/lib/api/client";
import type { Finding } from "@/lib/api/types";

import { FindingsInboxPage } from "./FindingsInboxPage";

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f1",
    project_id: "p1",
    run_id: "run1",
    root_cause_key: "endpoint=POST api/orders#fail|status=500",
    title: "Orders accepted without authentication",
    layer: "api",
    severity: "critical",
    status: "new",
    oracle_source: "rule-derived",
    explains_count: 1,
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
    evidence: [],
    history: { classification: "new", occurrence_count: 1 },
    triage: { status: "open" },
    ...over,
  };
}

function openPage(items: Finding[], total: number) {
  return { ok: true, status: 200, data: { items, total, limit: 25, offset: 0 } };
}

describe("FindingsInboxPage", () => {
  beforeEach(() => vi.mocked(findingApi.listOpen).mockReset());

  it("lists open findings across projects with trust marks + badges", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      openPage(
        [
          finding({ id: "a", title: "Orders accepted without authentication" }),
          finding({
            id: "b",
            title: "Checkout fails on empty cart",
            severity: "major",
            oracle_source: "characterization",
            status: "regression",
          }),
        ],
        2,
      ),
    );

    render(<FindingsInboxPage />);

    const rowA = (
      await screen.findByText("Orders accepted without authentication")
    ).closest("button")!;
    expect(within(rowA).getByText("Critical")).toBeInTheDocument();
    expect(within(rowA).getByText("rule-derived")).toBeInTheDocument();

    const rowB = screen.getByText("Checkout fails on empty cart").closest("button")!;
    expect(within(rowB).getByText("characterization")).toBeInTheDocument();
    expect(within(rowB).getByText("Regression")).toBeInTheDocument();
  });

  it("filters the list by severity", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      openPage(
        [
          finding({ id: "a", title: "Critical one", severity: "critical" }),
          finding({ id: "b", title: "Minor one", severity: "minor" }),
        ],
        2,
      ),
    );

    render(<FindingsInboxPage />);
    await screen.findByText("Critical one");

    fireEvent.change(screen.getByLabelText("Severity"), {
      target: { value: "critical" },
    });

    expect(screen.getByText("Critical one")).toBeInTheDocument();
    expect(screen.queryByText("Minor one")).toBeNull();
  });

  it("opens the detail drawer when a finding is selected", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      openPage(
        [finding({ id: "a", title: "Orders accepted without authentication" })],
        1,
      ),
    );

    render(<FindingsInboxPage />);
    fireEvent.click(await screen.findByText("Orders accepted without authentication"));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows a clean state when nothing is open", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(openPage([], 0));
    render(<FindingsInboxPage />);
    expect(await screen.findByText("Nothing's broken right now")).toBeInTheDocument();
  });

  it("shows an error state when the inbox can't load", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue({
      ok: false,
      status: 503,
      data: null,
      error: "service_unavailable",
    });
    render(<FindingsInboxPage />);
    expect(await screen.findByText("Couldn't load findings")).toBeInTheDocument();
  });
});
