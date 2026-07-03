import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The journey logic is covered in RunJourney.test; here we only smoke the page shell
// (header + back link) and that it delegates to the journey view.
vi.mock("@/lib/api/client", () => ({
  runApi: { events: vi.fn(), get: vi.fn() },
  projectApi: { tests: vi.fn(), get: vi.fn() },
}));
vi.mock("./runEventsStream", () => ({ streamRunEvents: vi.fn() }));
vi.mock("./useRunScreenshot", () => ({
  useRunScreenshot: () => ({ url: null, state: "loading" }),
}));

import { projectApi, runApi } from "@/lib/api/client";

import { LiveRunView } from "./LiveRunView";

describe("LiveRunView", () => {
  beforeEach(() => {
    vi.mocked(projectApi.tests)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: { items: [], total: 0 },
      });
    vi.mocked(projectApi.get)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          id: "p1",
          name: "Acme API",
          slug: "acme",
          repo_url: "/r",
          app_url: null,
          auth_config_ref: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      });
    vi.mocked(runApi.events)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          run_id: "r1",
          events: [
            {
              seq: 1,
              phase: "generate",
              step: "Generate test",
              status: "passed",
              detail: null,
              timestamp: "2026-01-01T00:00:00Z",
            },
            {
              seq: 2,
              phase: "run",
              step: "run",
              status: "passed",
              detail: null,
              timestamp: "2026-01-01T00:00:01Z",
            },
          ],
        },
      });
    vi.mocked(runApi.get)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          run_id: "r1",
          project_id: "p1",
          mode: "mode_b",
          status: "succeeded",
          summary: null,
        },
      });
  });

  it("renders the page shell and the run journey tabs", async () => {
    render(<LiveRunView runId="r1" />);
    // Page chrome.
    expect(screen.getByText("Run journey")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Run overview/ }),
    ).toBeInTheDocument();
    // Delegates to RunJourney → the phase tablist renders.
    expect(
      await screen.findByRole("tablist", { name: "Run phases" }),
    ).toBeInTheDocument();
  });
});
