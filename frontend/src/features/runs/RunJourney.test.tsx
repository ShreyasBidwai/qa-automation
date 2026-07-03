import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  runApi: { events: vi.fn(), get: vi.fn() },
  projectApi: { tests: vi.fn(), get: vi.fn() },
}));
vi.mock("./runEventsStream", () => ({ streamRunEvents: vi.fn() }));
vi.mock("./useRunScreenshot", () => ({
  useRunScreenshot: () => ({ url: "blob:fake", state: "ready" }),
}));

import { projectApi, runApi } from "@/lib/api/client";
import type {
  JobStatusValue,
  RunProgressEvent,
  TestCaseSummary,
} from "@/lib/api/types";

import { RunJourney } from "./RunJourney";
import { streamRunEvents } from "./runEventsStream";

function event(
  over: Partial<RunProgressEvent> & { seq: number },
): RunProgressEvent {
  return {
    phase: "execute",
    step: "step",
    status: "passed",
    detail: null,
    timestamp: "2026-01-01T00:00:00Z",
    ...over,
  };
}

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
  }),
  event({
    seq: 3,
    phase: "execute",
    step: "POST api/orders returns 201",
    status: "failed",
    detail: { endpoint: "POST api/orders", expected: 201, actual: 500 },
    has_screenshot: true,
  }),
  event({ seq: 4, phase: "review", step: "Review complete", status: "passed" }),
  event({ seq: 5, phase: "run", step: "run", status: "failed" }),
];

function eventsResponse(events: RunProgressEvent[]) {
  return { ok: true, status: 200, data: { run_id: "r1", events } };
}

function runStatus(status: JobStatusValue) {
  return {
    ok: true,
    status: 200,
    data: {
      run_id: "r1",
      project_id: "p1",
      mode: "mode_b",
      status,
      summary: null,
    },
  };
}

function testCase(over: Partial<TestCaseSummary> = {}): TestCaseSummary {
  return {
    id: "t1",
    target: "POST api/orders",
    type: "happy",
    layer: "api",
    oracle_source: "characterization",
    framework: "pest",
    code: "<?php\n// Intent: creates an order\nclass Orders_Test {}\n",
    created_at: "2026-01-01T00:00:00Z",
    origin: "generated",
    proposal_status: null,
    ...over,
  };
}

function testsOk(items: TestCaseSummary[]) {
  return { ok: true, status: 200, data: { items, total: items.length } };
}

function projectOk() {
  return {
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
  };
}

describe("RunJourney", () => {
  beforeEach(() => {
    vi.mocked(runApi.events).mockReset();
    vi.mocked(runApi.get).mockReset().mockResolvedValue(runStatus("succeeded"));
    vi.mocked(projectApi.get).mockReset().mockResolvedValue(projectOk());
    vi.mocked(streamRunEvents).mockReset();
    vi.mocked(projectApi.tests)
      .mockReset()
      .mockResolvedValue(testsOk([testCase()]));
  });

  it("shows every phase as a tab and defaults to the active phase", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY));

    render(<RunJourney runId="r1" />);
    await screen.findByText("Run failed");

    for (const label of [
      "Understand",
      "Generate",
      "Execute",
      "Explore live site",
      "Review",
    ]) {
      expect(
        screen.getByRole("tab", { name: new RegExp(label) }),
      ).toBeInTheDocument();
    }
    // The project this run belongs to is named at the top.
    expect(await screen.findByText("Acme API")).toBeInTheDocument();
    // A finished run defaults to the last active phase (Review) — only ITS content is
    // shown, so the Execute step is not visible until that tab is opened.
    expect(screen.getByText("Review complete")).toBeInTheDocument();
    expect(screen.queryByText("POST api/orders returns 201")).toBeNull();
    // Terminal outcome + findings affordance; replay only, no live stream.
    expect(
      screen.getByRole("link", { name: "View findings" }),
    ).toBeInTheDocument();
    expect(streamRunEvents).not.toHaveBeenCalled();
  });

  it("switches to a phase's steps on tab click (and auto-reveals a failing shot)", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY));

    render(<RunJourney runId="r1" />);
    fireEvent.click(await screen.findByRole("tab", { name: /Execute/ }));

    expect(
      await screen.findByText("POST api/orders returns 201"),
    ).toBeInTheDocument();
    // The failing step captured a screenshot → it auto-reveals.
    expect(await screen.findByText("Hide screenshot")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Screenshot for step #3/ }),
    ).toBeInTheDocument();
  });

  it("links through to the generated-tests page from the Generate phase", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(JOURNEY));

    render(<RunJourney runId="r1" />);
    fireEvent.click(await screen.findByRole("tab", { name: /Generate/ }));

    // A single "View generated tests" link opens the full tests page (no per-test
    // popup here); the authored count is surfaced.
    const link = await screen.findByRole("link", {
      name: /View generated tests/,
    });
    expect(link).toHaveAttribute("href", "/projects/p1/tests");
    expect(screen.getByText(/Polaris authored 1 test/)).toBeInTheDocument();
  });

  it("shows the live watching state for an in-progress run", async () => {
    vi.mocked(runApi.events).mockResolvedValue(
      eventsResponse(JOURNEY.slice(0, 3)),
    );
    vi.mocked(streamRunEvents).mockReturnValue(new Promise<void>(() => {}));

    render(<RunJourney runId="r1" />);

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/watching live/)).toBeInTheDocument();
    // The in-flight step (Execute) is the default phase, so it shows.
    expect(screen.getByText("Execute 1 test")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View findings" })).toBeNull();
  });

  it("shows the live browser frame in the Explore phase", async () => {
    const crawl: RunProgressEvent[] = [
      event({ seq: 0, phase: "run", step: "run", status: "started" }),
      event({
        seq: 1,
        phase: "crawl",
        step: "Visited /orders",
        status: "passed",
        detail: { url: "http://app/orders" },
        has_screenshot: true,
      }),
      event({ seq: 2, phase: "run", step: "run", status: "passed" }),
    ];
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse(crawl));

    render(<RunJourney runId="r1" />);
    await screen.findByText("Run passed");

    // Explore is the last active phase → default → the browser frame shows.
    expect(
      screen.getByRole("img", {
        name: /What Polaris saw at http:\/\/app\/orders/,
      }),
    ).toBeInTheDocument();
  });

  it("surfaces a reconnect affordance when the stream can't be reached", async () => {
    vi.mocked(runApi.events).mockResolvedValue(eventsResponse([]));
    vi.mocked(streamRunEvents).mockRejectedValue(new Error("network"));
    vi.mocked(runApi.get).mockResolvedValue({
      ok: false,
      status: 0,
      data: null,
      error: "network",
    });

    render(<RunJourney runId="r1" />);

    expect(
      await screen.findByText("Couldn't load the run journey"),
    ).toBeInTheDocument();
    expect(
      within(document.body).getByRole("button", { name: "Reconnect" }),
    ).toBeInTheDocument();
  });
});
