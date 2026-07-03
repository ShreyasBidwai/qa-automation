import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  projectApi: { get: vi.fn(), ingest: vi.fn(), model: vi.fn() },
  runApi: { list: vi.fn() },
  findingApi: { listForProject: vi.fn() },
  jobApi: { get: vi.fn() },
}));

import { findingApi, projectApi, runApi } from "@/lib/api/client";
import type { Finding, Project, RunListItem } from "@/lib/api/types";

import { ProjectPage } from "./ProjectPage";

const PROJECT: Project = {
  id: "p1",
  name: "Acme Billing API",
  slug: "acme-billing",
  repo_url: "https://github.com/acme/billing.git",
  app_url: "https://staging.acme.com",
  auth_config_ref: null,
  stack: "Laravel",
  created_at: "2026-06-01T00:00:00Z",
};

function run(over: Partial<RunListItem>): RunListItem {
  return {
    id: "r1",
    mode: "B",
    status: "passed",
    created_at: "2026-06-22T11:00:00Z",
    pass_rate: 0.78,
    ...over,
  };
}

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f1",
    project_id: "p1",
    run_id: "r1",
    root_cause_key: "k",
    title: "A finding",
    layer: "api",
    severity: "critical",
    status: "new",
    oracle_source: "rule-derived",
    explains_count: 1,
    ...over,
  };
}

function ok<T>(data: T) {
  return { ok: true, status: 200, data };
}

describe("ProjectPage (overview)", () => {
  beforeEach(() => {
    vi.mocked(projectApi.get).mockReset();
    vi.mocked(runApi.list).mockReset();
    vi.mocked(findingApi.listForProject).mockReset();
    vi.mocked(projectApi.model)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          built: false,
          node_count: 0,
          edge_count: 0,
          nodes_by_kind: [],
          last_built_at: null,
        },
      });
  });

  it("renders the health summary, config, and recent runs", async () => {
    vi.mocked(projectApi.get).mockResolvedValue(ok(PROJECT));
    vi.mocked(runApi.list).mockResolvedValue(
      ok({
        items: [
          run({ id: "r1", pass_rate: 0.78 }),
          run({ id: "r2", pass_rate: 0.7, status: "failed" }),
        ],
        total: 2,
        limit: 5,
        offset: 0,
      }),
    );
    vi.mocked(findingApi.listForProject).mockResolvedValue(
      ok({
        items: [
          finding({ id: "a", severity: "critical" }),
          finding({ id: "b", severity: "major" }),
          finding({ id: "c", severity: "minor" }),
        ],
        total: 3,
        limit: 50,
        offset: 0,
      }),
    );

    render(<ProjectPage projectId="p1" />);

    // Health summary (78% also shows on the latest run's row, so allow >1).
    expect((await screen.findAllByText("78%")).length).toBeGreaterThanOrEqual(
      1,
    );
    expect(screen.getByText("Open findings")).toBeInTheDocument();
    expect(screen.getByText("1 critical")).toBeInTheDocument();

    // Config + actions.
    expect(screen.getByText("Laravel")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "https://staging.acme.com" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit" })).toBeInTheDocument();

    // Recent runs.
    expect(screen.getByText("Recent runs")).toBeInTheDocument();
  });

  it("shows the built-model summary with node/edge counts and kinds", async () => {
    vi.mocked(projectApi.get).mockResolvedValue(ok(PROJECT));
    vi.mocked(runApi.list).mockResolvedValue(
      ok({ items: [], total: 0, limit: 5, offset: 0 }),
    );
    vi.mocked(findingApi.listForProject).mockResolvedValue(
      ok({ items: [], total: 0, limit: 50, offset: 0 }),
    );
    vi.mocked(projectApi.model).mockResolvedValue(
      ok({
        built: true,
        node_count: 3,
        edge_count: 1,
        nodes_by_kind: [
          { kind: "endpoint", count: 2 },
          { kind: "page", count: 1 },
        ],
        last_built_at: "2026-06-22T11:00:00Z",
      }),
    );

    render(<ProjectPage projectId="p1" />);

    expect(await screen.findByText("Model built")).toBeInTheDocument();
    expect(screen.getByText(/3 nodes/)).toBeInTheDocument();
    expect(screen.getByText(/1 edge/)).toBeInTheDocument();
    expect(screen.getByText("Endpoints")).toBeInTheDocument();
    // A built model offers a rebuild, not a first build.
    expect(
      screen.getByRole("button", { name: "Rebuild model" }),
    ).toBeInTheDocument();
  });

  it("surfaces the Gitea + PM connectors as coming soon", async () => {
    vi.mocked(projectApi.get).mockResolvedValue(ok(PROJECT));
    vi.mocked(runApi.list).mockResolvedValue(
      ok({ items: [], total: 0, limit: 5, offset: 0 }),
    );
    vi.mocked(findingApi.listForProject).mockResolvedValue(
      ok({ items: [], total: 0, limit: 50, offset: 0 }),
    );

    render(<ProjectPage projectId="p1" />);

    expect(await screen.findByText("Connectors")).toBeInTheDocument();
    expect(screen.getByText("Gitea")).toBeInTheDocument();
    expect(screen.getByText("Project management")).toBeInTheDocument();
    expect(screen.getAllByText("Coming soon")).toHaveLength(2);
  });

  it("shows an error state when the project can't be loaded", async () => {
    vi.mocked(projectApi.get).mockResolvedValue({
      ok: false,
      status: 404,
      data: null,
      error: "Project not found.",
    });
    vi.mocked(runApi.list).mockResolvedValue(
      ok({ items: [], total: 0, limit: 5, offset: 0 }),
    );
    vi.mocked(findingApi.listForProject).mockResolvedValue(
      ok({ items: [], total: 0, limit: 50, offset: 0 }),
    );

    render(<ProjectPage projectId="p1" />);

    expect(
      await screen.findByText("Couldn't load this project"),
    ).toBeInTheDocument();
  });
});
