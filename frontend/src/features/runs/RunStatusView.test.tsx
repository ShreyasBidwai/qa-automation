import { render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ runApi: { get: vi.fn() } }));

import { runApi } from "@/lib/api/client";
import type { JobStatusValue } from "@/lib/api/types";

import { RunStatusView } from "./RunStatusView";
import { POLL_INTERVAL_MS } from "./useRunStatus";

function runStatus(status: JobStatusValue) {
  return {
    ok: true,
    status: 200,
    data: { run_id: "r1", mode: "mode_b", status, summary: null },
  };
}

describe("RunStatusView", () => {
  beforeEach(() => {
    vi.mocked(runApi.get).mockReset();
  });

  it("renders the done state with a link to findings on success", async () => {
    vi.mocked(runApi.get).mockResolvedValue(runStatus("succeeded"));
    render(<RunStatusView runId="r1" />);

    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View findings" })).toBeInTheDocument();
  });

  it("renders the failed state", async () => {
    vi.mocked(runApi.get).mockResolvedValue(runStatus("failed"));
    render(<RunStatusView runId="r1" />);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View findings" })).toBeNull();
  });

  describe("while polling", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows running, then transitions to done", async () => {
      vi.mocked(runApi.get)
        .mockResolvedValueOnce(runStatus("running"))
        .mockResolvedValue(runStatus("succeeded"));

      render(<RunStatusView runId="r1" />);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0); // flush the first poll
      });
      expect(screen.getByText("Running…")).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); // next poll
      });
      expect(screen.getByText("Done")).toBeInTheDocument();
    });
  });
});
