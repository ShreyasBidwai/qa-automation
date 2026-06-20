import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  projectApi: { list: vi.fn() },
  runApi: { list: vi.fn() },
}));

import { projectApi, runApi } from "@/lib/api/client";
import type { ProjectListItem, RunListItem } from "@/lib/api/types";

import { RunsListPage } from "./RunsListPage";

const PROJECTS: ProjectListItem[] = [
  {
    id: "p1",
    name: "Alpha",
    slug: "alpha",
    repo_url: "r",
    app_url: null,
    created_at: "2026-01-01",
  },
];

function run(over: Partial<RunListItem>): RunListItem {
  return {
    id: "run1",
    mode: "B",
    status: "passed",
    created_at: "2026-01-01T00:00:00Z",
    pass_rate: 0.8,
    ...over,
  };
}

function projectsPage(items: ProjectListItem[]) {
  return {
    ok: true,
    status: 200,
    data: { items, total: items.length, limit: 100, offset: 0 },
  };
}

function runsPage(items: RunListItem[], total: number) {
  return { ok: true, status: 200, data: { items, total, limit: 20, offset: 0 } };
}

describe("RunsListPage", () => {
  beforeEach(() => {
    vi.mocked(projectApi.list).mockReset();
    vi.mocked(runApi.list).mockReset();
  });

  it("renders the selected project's runs with mode labels, status, pass rate", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(projectsPage(PROJECTS));
    vi.mocked(runApi.list).mockResolvedValue(
      runsPage(
        [
          run({ id: "r1", mode: "B", status: "passed", pass_rate: 0.8 }),
          run({ id: "r2", mode: "C", status: "failed", pass_rate: 0 }),
        ],
        2,
      ),
    );

    render(<RunsListPage />);

    expect(await screen.findByText("Autonomous (Mode B)")).toBeInTheDocument();
    expect(screen.getByText("Natural language (Mode C)")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(runApi.list).toHaveBeenCalledWith("p1", { limit: 20, offset: 0 });
  });

  it("shows an empty state when the project has no runs", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(projectsPage(PROJECTS));
    vi.mocked(runApi.list).mockResolvedValue(runsPage([], 0));
    render(<RunsListPage />);
    expect(await screen.findByText("No runs for this project")).toBeInTheDocument();
  });

  it("shows an empty state when there are no projects", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(projectsPage([]));
    render(<RunsListPage />);
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(runApi.list).not.toHaveBeenCalled();
  });

  it("renders an error state when runs fail to load", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(projectsPage(PROJECTS));
    vi.mocked(runApi.list).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "nope",
    });
    render(<RunsListPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load runs.");
  });

  it("pages runs with the right offset/limit", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(projectsPage(PROJECTS));
    vi.mocked(runApi.list).mockResolvedValue(runsPage([run({ id: "r1" })], 25));

    render(<RunsListPage />);
    await screen.findByText("Autonomous (Mode B)");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(runApi.list).toHaveBeenLastCalledWith("p1", { limit: 20, offset: 20 }),
    );
  });
});
