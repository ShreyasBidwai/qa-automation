import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ runApi: { events: vi.fn(), get: vi.fn() } }));
vi.mock("./runEventsStream", () => ({ streamRunEvents: vi.fn() }));
// Screenshot bytes come from an authorized fetch → object URL; stub the hook so the
// component renders the <img> without a real network/blob round-trip.
vi.mock("./useRunScreenshot", () => ({
  useRunScreenshot: () => ({ url: "blob:fake", state: "ready" }),
}));

import { runApi } from "@/lib/api/client";
import type { RunProgressEvent } from "@/lib/api/types";

import { LiveRunView } from "./LiveRunView";
import { streamRunEvents } from "./runEventsStream";

function event(over: Partial<RunProgressEvent> & { seq: number }): RunProgressEvent {
  return {
    phase: "execute",
    step: "step",
    status: "passed",
    detail: null,
    timestamp: "2026-01-01T00:00:00Z",
    ...over,
  };
}

// The stub demo journey (mirrors backend/app/api/composition.py).
const JOURNEY: RunProgressEvent[] = [
  event({ seq: 0, phase: "run", step: "run", status: "started" }),
  event({
    seq: 1,
    phase: "generate",
    step: "Generate test for POST api/orders",
    status: "passed",
    detail: { endpoint: "POST api/orders" },
  }),
  event({
    seq: 2,
    phase: "execute",
    step: "Execute 1 test",
    status: "started",
    detail: { tests: 1 },
  }),
  event({
    seq: 3,
    phase: "execute",
    step: "POST api/orders returns 201",
    status: "failed",
    detail: { endpoint: "POST api/orders", expected: 201, actual: 500 },
  }),
  event({
    seq: 4,
    phase: "review",
    step: "Review complete",
    status: "passed",
    detail: { findings: 1 },
  }),
  event({
    seq: 5,
    phase: "run",
    step: "run",
    status: "failed",
    detail: { status: "failed" },
  }),
];

function eventsResponse(events: RunProgressEvent[]) {
  return { ok: true, status: 200, data: { run_id: "r1", events } };
}

describe("LiveRunView", () => {
  beforeEach(() => {
    vi.mocked(runApi.events).mockReset();
    vi.mocked(runApi.get).mockReset();
    vi.mocked(streamRunEvents).mockReset();
  });

  it("renders a finished run's journey from replay alone (no live stream)", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY));

    render(<LiveRunView runId="r1" />);

    // The phase spine (all four phases) and the real steps.
    expect(await screen.findByText("Understand")).toBeInTheDocument();
    expect(screen.getByText("Generate")).toBeInTheDocument();
    expect(screen.getByText("Execute")).toBeInTheDocument();
    expect(screen.getByText("Review")).toBeInTheDocument();
    expect(screen.getByText("POST api/orders returns 201")).toBeInTheDocument();
    // Terminal run event drives the outcome banner + the findings affordance.
    expect(screen.getByText("Run failed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View findings" })).toBeInTheDocument();
    // A finished run needs no stream — replay is the whole story.
    expect(streamRunEvents).not.toHaveBeenCalled();
    // The list announces to assistive tech.
    expect(screen.getByRole("log", { name: "Run progress" })).toBeInTheDocument();
  });

  it("auto-expands the failing step's screenshot when it captured one", async () => {
    // The failing execute step (seq 3) carries a screenshot; nothing else does.
    const withShot = JOURNEY.map((e) =>
      e.seq === 3 ? { ...e, has_screenshot: true } : e,
    );
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(withShot));

    render(<LiveRunView runId="r1" />);
    await screen.findByText("Run failed");

    // The failing step auto-reveals → its screenshot image is shown. The reveal is a
    // useEffect, so await it (findBy) — a sync getBy races it under full-suite load.
    expect(await screen.findByText("Hide screenshot")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Screenshot for step #3/ }),
    ).toBeInTheDocument();
    // A step with no captured screenshot offers no toggle at all (nothing to show).
    expect(screen.queryByText("Show screenshot")).toBeNull();
  });

  it("shows the live browser frame for the latest captured page", async () => {
    const withCrawl: RunProgressEvent[] = [
      event({ seq: 0, phase: "run", step: "run", status: "started" }),
      event({
        seq: 1,
        phase: "crawl",
        step: "Visited /",
        status: "passed",
        detail: { url: "http://app/" },
        has_screenshot: true,
      }),
      event({
        seq: 2,
        phase: "crawl",
        step: "Visited /orders",
        status: "passed",
        detail: { url: "http://app/orders" },
        has_screenshot: true,
      }),
      event({ seq: 3, phase: "run", step: "run", status: "passed" }),
    ];
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(withCrawl));

    render(<LiveRunView runId="r1" />);
    await screen.findByText("Run passed");

    // The browser frame shows the MOST RECENT crawled page's screenshot (the alt
    // carries its URL) — the operator watches the crawl advance page-by-page. The
    // earlier page (/) is NOT the frame.
    expect(
      screen.getByRole("img", { name: /What Polaris saw at http:\/\/app\/orders/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: /What Polaris saw at http:\/\/app\/$/ }),
    ).toBeNull();
  });

  it("seeds from replay then appends live events from the stream", async () => {
    // Replay catches up only the first two events (run not yet terminal)…
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY.slice(0, 2)));
    // …then the stream delivers the rest, including the terminal event.
    vi.mocked(streamRunEvents).mockImplementation(async (_runId, { onEvents }) => {
      onEvents(JOURNEY.slice(2));
    });

    render(<LiveRunView runId="r1" />);

    // A step that only arrived over the stream is rendered.
    expect(await screen.findByText("POST api/orders returns 201")).toBeInTheDocument();
    expect(screen.getByText("Review complete")).toBeInTheDocument();
    expect(screen.getByText("Run failed")).toBeInTheDocument();
    expect(streamRunEvents).toHaveBeenCalledTimes(1);
  });

  it("shows the live, watching state while a run is still in progress", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY.slice(0, 3)));
    // The stream stays open (no terminal) — the run is ongoing.
    vi.mocked(streamRunEvents).mockReturnValue(new Promise<void>(() => {}));

    render(<LiveRunView runId="r1" />);

    expect(await screen.findByText("Running — watching live")).toBeInTheDocument();
    // The in-flight step is shown under Execute.
    expect(screen.getByText("Execute 1 test")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View findings" })).toBeNull();
  });

  it("surfaces a reconnect affordance when the stream can't be reached", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse([]));
    vi.mocked(streamRunEvents).mockRejectedValue(new Error("network"));
    // Backend unreachable → the status probe fails too, so we surface the error
    // (a manual Reconnect) rather than looping on a dead endpoint.
    vi.mocked(runApi.get).mockResolvedValue({
      ok: false,
      status: 0,
      data: null,
      error: "network",
    });

    render(<LiveRunView runId="r1" />);

    const panel = await screen.findByText("Couldn't load the run journey");
    expect(panel).toBeInTheDocument();
    expect(
      within(document.body).getByRole("button", { name: "Reconnect" }),
    ).toBeInTheDocument();
  });

  it("re-opens the stream (never 'Run ended') when a long run is still going", async () => {
    vi.useFakeTimers();
    try {
      // A mid-run journey with no terminal event yet…
      vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY.slice(0, 3)));
      // …the SSE stream closes cleanly WITHOUT a terminal (the ~5-min safety cap)…
      vi.mocked(streamRunEvents).mockResolvedValue(undefined);
      // …but the authoritative job status says the run is still running.
      vi.mocked(runApi.get).mockResolvedValue({
        ok: true,
        status: 200,
        data: { run_id: "r1", mode: "mode_b", status: "running", summary: null },
      });

      render(<LiveRunView runId="r1" />);

      // Initial load: replay → stream closes → status probe → schedules a reconnect.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(streamRunEvents).toHaveBeenCalledTimes(1);
      // The run is NOT over — it must never settle to a terminal "Run ended" banner.
      expect(screen.queryByText("Run ended")).toBeNull();

      // The reconnect beat fires → the stream re-opens on its own.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1300);
      });
      expect(streamRunEvents).toHaveBeenCalledTimes(2);
      expect(screen.queryByText("Run ended")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
