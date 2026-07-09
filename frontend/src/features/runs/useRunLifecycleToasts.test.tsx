import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ runApi: { active: vi.fn(), get: vi.fn() } }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { ToastProvider } from "@/components/ToastProvider";
import { runApi } from "@/lib/api/client";
import { navigate } from "@/lib/router";

import { useRunLifecycleToasts } from "./useRunLifecycleToasts";

const POLL_MS = 4000;

function activeRun(runId: string | null) {
  return {
    ok: true,
    status: 200,
    data: {
      run_id: runId,
      project_id: runId ? "p1" : null,
      mode: runId ? "mode_b" : null,
      status: runId ? ("running" as const) : null,
    },
  };
}

function runStatus(status: "succeeded" | "failed") {
  return {
    ok: true,
    status: 200,
    data: { run_id: "r1", project_id: "p1", mode: "mode_b", status, summary: null },
  };
}

function Harness() {
  useRunLifecycleToasts();
  return null;
}

function renderHarness() {
  return render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
}

describe("useRunLifecycleToasts", () => {
  beforeEach(() => {
    vi.mocked(runApi.active).mockReset();
    vi.mocked(runApi.get).mockReset();
    vi.mocked(navigate).mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays quiet while a run is merely active (no completion yet)", async () => {
    vi.mocked(runApi.active).mockResolvedValue(activeRun("r1"));
    renderHarness();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0); // flush the first poll
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    expect(screen.queryByRole("status")).toBeNull();
    expect(runApi.get).not.toHaveBeenCalled();
  });

  it("toasts a success when the active run disappears having succeeded", async () => {
    vi.mocked(runApi.active)
      .mockResolvedValueOnce(activeRun("r1"))
      .mockResolvedValue(activeRun(null));
    vi.mocked(runApi.get).mockResolvedValue(runStatus("succeeded"));
    renderHarness();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });

    const toast = screen.getByRole("status");
    expect(toast).toHaveTextContent("Run completed");

    fireEvent.click(screen.getByRole("button", { name: "View" }));
    expect(navigate).toHaveBeenCalledWith("/runs/r1/findings");
  });

  it("toasts a failure when the active run disappears having failed", async () => {
    vi.mocked(runApi.active)
      .mockResolvedValueOnce(activeRun("r1"))
      .mockResolvedValue(activeRun(null));
    vi.mocked(runApi.get).mockResolvedValue(runStatus("failed"));
    renderHarness();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Run failed");
  });

  it("re-arms for a second run in the same session", async () => {
    vi.mocked(runApi.active)
      .mockResolvedValueOnce(activeRun("r1")) // poll 1: run 1 active
      .mockResolvedValueOnce(activeRun(null)) // poll 2: run 1 gone
      .mockResolvedValueOnce(activeRun("r2")) // poll 3: run 2 active
      .mockResolvedValue(activeRun(null)); // poll 4: run 2 gone
    vi.mocked(runApi.get)
      .mockResolvedValueOnce(runStatus("succeeded"))
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          run_id: "r2",
          project_id: "p1",
          mode: "mode_b",
          status: "failed",
          summary: null,
        },
      });
    renderHarness();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS); // run 1 finishes
    });
    expect(screen.getByText("Run completed")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS); // run 2 picked up
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS); // run 2 finishes
    });
    expect(screen.getByText("Run failed")).toBeInTheDocument();
  });
});
