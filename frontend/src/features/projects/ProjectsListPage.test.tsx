import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ projectApi: { list: vi.fn() } }));

import { projectApi } from "@/lib/api/client";
import type { ProjectListItem } from "@/lib/api/types";

import { ProjectsListPage } from "./ProjectsListPage";

function project(over: Partial<ProjectListItem>): ProjectListItem {
  return {
    id: "p1",
    name: "Demo",
    slug: "demo-1",
    repo_url: "https://git/x.git",
    app_url: null,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function page(items: ProjectListItem[], total: number) {
  return { ok: true, status: 200, data: { items, total, limit: 20, offset: 0 } };
}

describe("ProjectsListPage", () => {
  beforeEach(() => vi.mocked(projectApi.list).mockReset());

  it("renders projects from the list endpoint", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(
      page(
        [project({ id: "a", name: "Alpha" }), project({ id: "b", name: "Beta" })],
        2,
      ),
    );

    render(<ProjectsListPage />);

    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(projectApi.list).toHaveBeenCalledWith({ limit: 20, offset: 0 });
  });

  it("renders the enriched summary columns and the honest never-run treatment", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(
      page(
        [
          project({
            id: "a",
            name: "Acme Billing API",
            stack: "Laravel",
            status: "action_needed",
            open_findings_count: 12,
            last_run: {
              run_id: "run1",
              mode: "B",
              status: "failed",
              pass_rate: 0.78,
              finished_at: "2026-06-22T11:00:00Z",
              created_at: "2026-06-22T11:00:00Z",
            },
          }),
          project({ id: "b", name: "Fresh Project" }), // no runs → never_run defaults
        ],
        2,
      ),
    );

    render(<ProjectsListPage />);

    const rowA = (await screen.findByText("Acme Billing API")).closest("a")!;
    expect(within(rowA).getByText("Laravel")).toBeInTheDocument();
    expect(within(rowA).getByText("78%")).toBeInTheDocument();
    expect(within(rowA).getByText("12")).toBeInTheDocument();
    expect(within(rowA).getByText("Action needed")).toBeInTheDocument();

    // A project with no runs is honest, not fabricated.
    const rowB = screen.getByText("Fresh Project").closest("a")!;
    expect(within(rowB).getByText("No runs yet")).toBeInTheDocument();
    expect(within(rowB).getByText("Never run")).toBeInTheDocument();
  });

  it("renders the empty state when there are no projects", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(page([], 0));
    render(<ProjectsListPage />);
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  });

  it("renders the loading state while fetching", async () => {
    // A deferred promise (resolved before the test ends, so nothing dangles).
    let resolve!: (value: Awaited<ReturnType<typeof projectApi.list>>) => void;
    vi.mocked(projectApi.list).mockReturnValue(
      new Promise<Awaited<ReturnType<typeof projectApi.list>>>((r) => {
        resolve = r;
      }),
    );

    render(<ProjectsListPage />);
    expect(screen.getByText("Loading projects…")).toBeInTheDocument();

    resolve(page([], 0));
    await screen.findByText("No projects yet");
  });

  it("renders an error state", async () => {
    vi.mocked(projectApi.list).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "boom",
    });
    render(<ProjectsListPage />);
    expect(await screen.findByText("Couldn't load projects")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("pages with the right offset/limit", async () => {
    vi.mocked(projectApi.list).mockResolvedValue(
      page([project({ id: "a", name: "Alpha" })], 25),
    );

    render(<ProjectsListPage />);
    await screen.findByText("Alpha");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(projectApi.list).toHaveBeenLastCalledWith({ limit: 20, offset: 20 }),
    );
  });
});
