import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  runApi: { active: vi.fn(), events: vi.fn(), get: vi.fn() },
  projectApi: { tests: vi.fn() },
}));
vi.mock("./runEventsStream", () => ({ streamRunEvents: vi.fn() }));
vi.mock("./useRunScreenshot", () => ({
  useRunScreenshot: () => ({ url: null, state: "loading" }),
}));

import { projectApi, runApi } from "@/lib/api/client";

import { OngoingRunPage } from "./OngoingRunPage";

const NO_RUN = {
  ok: true,
  status: 200,
  data: { run_id: null, project_id: null, mode: null, status: null },
};

describe("OngoingRunPage", () => {
  beforeEach(() => {
    vi.mocked(runApi.active).mockReset();
    vi.mocked(runApi.events)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          run_id: "r1",
          // At least one event so the journey leaves the loading skeleton and the
          // phase tablist renders (a running run with no events keeps reconnecting).
          events: [
            {
              seq: 1,
              phase: "select",
              step: "Selecting targets",
              status: "started",
              detail: null,
              timestamp: "2026-01-01T00:00:00Z",
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
          status: "running",
          summary: null,
        },
      });
    vi.mocked(projectApi.tests)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: { items: [], total: 0 },
      });
  });

  it("shows an honest empty state when nothing is running", async () => {
    vi.mocked(runApi.active).mockResolvedValue(NO_RUN);
    render(<OngoingRunPage />);
    expect(await screen.findByText("No run in progress")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Start a run" }),
    ).toBeInTheDocument();
  });

  it("renders the run journey once an active run is found", async () => {
    vi.mocked(runApi.active).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        run_id: "r1",
        project_id: "p1",
        mode: "mode_b",
        status: "running",
      },
    });
    render(<OngoingRunPage />);
    // Resolves the active run → mounts RunJourney → the phase tablist appears.
    expect(
      await screen.findByRole("tablist", { name: "Run phases" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("No run in progress")).toBeNull();
  });
});
