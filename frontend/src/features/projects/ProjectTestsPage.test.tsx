import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ projectApi: { tests: vi.fn() } }));

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
    ...over,
  };
}

function ok(items: TestCaseSummary[]) {
  return { ok: true, status: 200, data: { items, total: items.length } };
}

describe("ProjectTestsPage", () => {
  beforeEach(() => vi.mocked(projectApi.tests).mockReset());

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
});
