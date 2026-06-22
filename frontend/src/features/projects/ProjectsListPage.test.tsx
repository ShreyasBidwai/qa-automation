import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
