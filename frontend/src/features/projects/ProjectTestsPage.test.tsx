import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  projectApi: {
    tests: vi.fn(),
    acceptTest: vi.fn(),
    discardTest: vi.fn(),
  },
  jobApi: { get: vi.fn() },
}));

import { projectApi } from "@/lib/api/client";
import type { TestCaseSummary } from "@/lib/api/types";

import { ProjectTestsPage } from "./ProjectTestsPage";

function testCase(over: Partial<TestCaseSummary> = {}): TestCaseSummary {
  return {
    id: "t1",
    target: "GET api/orders",
    type: "happy",
    layer: "api",
    oracle_source: "characterization",
    framework: "pest",
    code: "<?php\nclass Orders_ShapeTest extends TestCase {}\n",
    created_at: "2026-01-01T00:00:00Z",
    origin: "generated",
    proposal_status: null,
    ...over,
  };
}

function ok(items: TestCaseSummary[]) {
  return { ok: true, status: 200, data: { items, total: items.length } };
}

describe("ProjectTestsPage", () => {
  beforeEach(() => {
    vi.mocked(projectApi.tests).mockReset();
    vi.mocked(projectApi.acceptTest).mockReset();
    vi.mocked(projectApi.discardTest).mockReset();
    // The page reads ?run / ?authoring off the URL — start each test from a clean one.
    window.history.replaceState({}, "", "/projects/p1/tests");
  });

  it("lists generated tests and reveals the runnable code on click", async () => {
    vi.mocked(projectApi.tests).mockResolvedValue(ok([testCase()]));

    render(<ProjectTestsPage projectId="p1" />);

    // The human-readable target shows; the code is hidden until the row is opened.
    const row = await screen.findByRole("button", { name: /GET api\/orders/ });
    expect(screen.queryByText(/Orders_ShapeTest/)).toBeNull();
    fireEvent.click(row);
    expect(screen.getByText(/Orders_ShapeTest/)).toBeInTheDocument();
  });

  it("filters by kind", async () => {
    vi.mocked(projectApi.tests).mockResolvedValue(
      ok([
        testCase({ id: "a", type: "happy", target: "GET a" }),
        testCase({ id: "b", type: "negative", target: "GET b" }),
      ]),
    );

    render(<ProjectTestsPage projectId="p1" />);
    expect(await screen.findByRole("button", { name: /GET a/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /GET b/ })).toBeInTheDocument();

    // Clicking the "Negative" filter chip narrows to the failure-path test only.
    fireEvent.click(screen.getByRole("button", { name: /^Negative/ }));
    expect(screen.queryByRole("button", { name: /GET a/ })).toBeNull();
    expect(screen.getByRole("button", { name: /GET b/ })).toBeInTheDocument();
  });

  it("scopes to a single run when opened with ?run and links back to all tests", async () => {
    window.history.replaceState({}, "", "/projects/p1/tests?run=run-9");
    vi.mocked(projectApi.tests).mockResolvedValue(ok([testCase()]));

    render(<ProjectTestsPage projectId="p1" />);

    // The run id is threaded to the API so only that run's cases load (ADR-0062).
    await vi.waitFor(() =>
      expect(projectApi.tests).toHaveBeenCalledWith("p1", "run-9"),
    );
    expect(
      screen.getByRole("heading", { name: "Tests from this run" }),
    ).toBeInTheDocument();
    // An escape hatch back to the project-wide list is always offered.
    expect(screen.getByRole("link", { name: "View all tests" })).toHaveAttribute(
      "href",
      "/projects/p1/tests",
    );
  });

  it("shows an empty state when nothing has been generated yet", async () => {
    vi.mocked(projectApi.tests).mockResolvedValue(ok([]));
    render(<ProjectTestsPage projectId="p1" />);
    expect(await screen.findByText("No tests yet")).toBeInTheDocument();
  });

  it("surfaces a load error honestly", async () => {
    vi.mocked(projectApi.tests).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "boom",
    });
    render(<ProjectTestsPage projectId="p1" />);
    expect(await screen.findByText("Couldn't load the tests")).toBeInTheDocument();
  });

  it("offers Accept/Discard on a pending proposal and reloads after accepting", async () => {
    const proposal = testCase({
      id: "p9",
      origin: "proposed",
      proposal_status: "pending",
    });
    // First load returns the pending proposal; after accepting, the reload returns
    // it as accepted (no longer offering the review controls).
    vi.mocked(projectApi.tests)
      .mockResolvedValueOnce(ok([proposal]))
      .mockResolvedValueOnce(ok([{ ...proposal, proposal_status: "accepted" }]));
    vi.mocked(projectApi.acceptTest).mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "p9", proposal_status: "accepted", is_current: true },
    });

    render(<ProjectTestsPage projectId="p1" />);
    const accept = await screen.findByRole("button", { name: "Accept" });
    expect(screen.getByText("Proposed")).toBeInTheDocument();

    fireEvent.click(accept);
    await vi.waitFor(() =>
      expect(projectApi.acceptTest).toHaveBeenCalledWith("p1", "p9"),
    );
    // The reload re-fetched the list (accept → reloadToken bump → useProjectTests).
    await vi.waitFor(() => expect(projectApi.tests).toHaveBeenCalledTimes(2));
  });
});
