import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  findingApi: { listOpen: vi.fn() },
  runApi: { triage: vi.fn() },
  projectApi: { list: vi.fn() },
}));

import { findingApi, projectApi } from "@/lib/api/client";
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

function projectItem(id: string, name: string) {
  return {
    id,
    name,
    slug: name.toLowerCase().replace(/\s+/g, "-"),
    repo_url: "https://example.test/repo",
    app_url: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function projectsPage(...projects: ReturnType<typeof projectItem>[]) {
  return {
    ok: true,
    status: 200,
    data: { items: projects, total: projects.length, limit: 100, offset: 0 },
  };
}

// The list (master) and the detail panel both render finding titles, so queries
// are scoped to a region to keep them unambiguous.
const listRegion = () => screen.findByRole("region", { name: "Findings" });

describe("FindingsInboxPage", () => {
  beforeEach(() => {
    vi.mocked(findingApi.listOpen).mockReset();
    vi.mocked(projectApi.list).mockReset();
    // The inbox loads the project-filter options on mount; default to two projects.
    vi.mocked(projectApi.list).mockResolvedValue(
      projectsPage(projectItem("p1", "Acme Billing"), projectItem("p2", "Storefront")),
    );
  });

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

    const list = await listRegion();
    const rowA = within(list)
      .getByText("Orders accepted without authentication")
      .closest("button")!;
    expect(within(rowA).getByText("Critical")).toBeInTheDocument();
    expect(within(rowA).getByText("rule-derived")).toBeInTheDocument();

    const rowB = within(list)
      .getByText("Checkout fails on empty cart")
      .closest("button")!;
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
    const list = await listRegion();

    fireEvent.change(within(list).getByLabelText("Severity"), {
      target: { value: "critical" },
    });

    expect(within(list).getByText("Critical one")).toBeInTheDocument();
    expect(within(list).queryByText("Minor one")).toBeNull();
  });

  it("filters the list by project (options from the projects the user can see)", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      openPage(
        [
          finding({ id: "a", title: "Acme issue", project_id: "p1" }),
          finding({ id: "b", title: "Storefront issue", project_id: "p2" }),
        ],
        2,
      ),
    );

    render(<FindingsInboxPage />);
    const list = await listRegion();

    // The Project pill appears once projectApi.list resolves; its options carry the
    // project names, and selecting one narrows the list by finding.project_id.
    const projectPill = await within(list).findByLabelText("Project");
    expect(within(projectPill).getByText("Acme Billing")).toBeInTheDocument();
    fireEvent.change(projectPill, { target: { value: "p1" } });

    expect(within(list).getByText("Acme issue")).toBeInTheDocument();
    expect(within(list).queryByText("Storefront issue")).toBeNull();
  });

  it("shows the selected finding's detail panel inline (the shared FindingDetail)", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      openPage(
        [finding({ id: "a", title: "Orders accepted without authentication" })],
        1,
      ),
    );

    render(<FindingsInboxPage />);

    // The first finding is selected on load — its detail (title + blast path) shows
    // without a click, in the same panel the run dashboard uses.
    const detail = await screen.findByRole("region", { name: "Finding detail" });
    expect(
      within(detail).getByRole("heading", {
        name: "Orders accepted without authentication",
      }),
    ).toBeInTheDocument();
    expect(within(detail).getByText("Blast path")).toBeInTheDocument();
  });

  it("updates the detail panel when another finding is selected", async () => {
    vi.mocked(findingApi.listOpen).mockResolvedValue(
      openPage(
        [
          finding({ id: "a", title: "Orders accepted without authentication" }),
          finding({
            id: "b",
            title: "Checkout fails on empty cart",
            severity: "major",
          }),
        ],
        2,
      ),
    );

    render(<FindingsInboxPage />);

    const list = await listRegion();
    fireEvent.click(
      within(list).getByText("Checkout fails on empty cart").closest("button")!,
    );

    const detail = screen.getByRole("region", { name: "Finding detail" });
    expect(
      within(detail).getByRole("heading", { name: "Checkout fails on empty cart" }),
    ).toBeInTheDocument();
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
