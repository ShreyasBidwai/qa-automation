import { describe, expect, it } from "vitest";

import type { RunProgressEvent } from "@/lib/api/types";

import {
  collapseSteps,
  currentStepSeq,
  detailEntries,
  formatDuration,
  frameLabel,
  groupByPhase,
  isTerminalEvent,
  latestScreenshotEvent,
  runElapsedMs,
  runOutcome,
} from "./runEvents";

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

describe("runEvents helpers", () => {
  it("treats only the run-level completion event as terminal", () => {
    expect(isTerminalEvent(event({ seq: 0, phase: "run", status: "failed" }))).toBe(
      true,
    );
    expect(isTerminalEvent(event({ seq: 1, phase: "run", status: "started" }))).toBe(
      false,
    );
    expect(isTerminalEvent(event({ seq: 2, phase: "execute", status: "failed" }))).toBe(
      false,
    );
  });

  it("groups into the spine (all known phases, run excluded, unknown appended)", () => {
    const groups = groupByPhase([
      event({ seq: 0, phase: "run", step: "run", status: "started" }),
      event({ seq: 1, phase: "generate", step: "gen" }),
      event({ seq: 2, phase: "deploy", step: "ship" }), // unknown phase
    ]);
    const keys = groups.map((g) => g.spec.key);
    // The spine phases always appear in journey order, then the unknown one; `run`
    // is never a group. The frontend crawl gets its own "Explore live site" phase.
    expect(keys).toEqual([
      "select",
      "generate",
      "execute",
      "crawl",
      "review",
      "deploy",
    ]);
    expect(groups.find((g) => g.spec.key === "generate")?.events).toHaveLength(1);
    expect(groups.find((g) => g.spec.key === "select")?.events).toHaveLength(0);
  });

  it("finds the latest event that has a screenshot (the live frame)", () => {
    expect(latestScreenshotEvent([event({ seq: 0 })])).toBeNull();
    const frame = latestScreenshotEvent([
      event({ seq: 0, phase: "crawl", has_screenshot: true }),
      event({ seq: 1, phase: "crawl", has_screenshot: true }),
      event({ seq: 2, phase: "review" }), // no shot — not the frame
    ]);
    expect(frame?.seq).toBe(1); // the most recent one WITH a screenshot
  });

  it("labels a frame by its crawled URL, falling back to the step", () => {
    expect(
      frameLabel(event({ seq: 0, step: "Visited /", detail: { url: "http://x/p" } })),
    ).toBe("http://x/p");
    expect(frameLabel(event({ seq: 1, step: "Visited /", detail: null }))).toBe(
      "Visited /",
    );
  });

  it("reads the run outcome from the last terminal event", () => {
    expect(runOutcome([event({ seq: 0, phase: "generate" })])).toBeNull();
    expect(
      runOutcome([
        event({ seq: 0, phase: "generate" }),
        event({ seq: 1, phase: "run", status: "failed" }),
      ]),
    ).toBe("failed");
  });

  it("marks the last unclosed started step as current, but nothing once finished", () => {
    const running = [
      event({ seq: 0, phase: "run", status: "started" }),
      event({ seq: 1, phase: "execute", status: "started" }),
    ];
    expect(currentStepSeq(running)).toBe(1);

    const finished = [...running, event({ seq: 2, phase: "run", status: "failed" })];
    expect(currentStepSeq(finished)).toBeNull();
  });

  it("renders detail as exactly the key/value pairs present", () => {
    expect(detailEntries({ expected: 201, actual: 500 })).toEqual([
      ["expected", "201"],
      ["actual", "500"],
    ]);
    expect(detailEntries(null)).toEqual([]);
  });

  it("collapses a step's started+terminal events into one row", () => {
    // The backend emits started THEN passed for the same step — the live view must
    // show ONE row (latest status), keeping first-seen order so it never reorders.
    const collapsed = collapseSteps([
      event({ seq: 0, phase: "generate", step: "Generate GET /a", status: "started" }),
      event({ seq: 1, phase: "generate", step: "Generate GET /a", status: "passed" }),
      event({ seq: 2, phase: "generate", step: "Generate POST /b", status: "started" }),
    ]);
    expect(collapsed.map((e) => [e.step, e.status])).toEqual([
      ["Generate GET /a", "passed"], // one row, latest status wins
      ["Generate POST /b", "started"], // still running → keeps its spinner
    ]);
  });

  it("groups collapse each phase's duplicate lifecycle events", () => {
    const gen = groupByPhase([
      event({ seq: 0, phase: "generate", step: "Generate GET /a", status: "started" }),
      event({ seq: 1, phase: "generate", step: "Generate GET /a", status: "passed" }),
    ]).find((g) => g.spec.key === "generate");
    expect(gen?.events).toHaveLength(1); // not two near-identical rows
  });

  it("measures elapsed wall time from the first to the last event", () => {
    expect(runElapsedMs([])).toBeNull();
    expect(
      runElapsedMs([
        event({ seq: 0, timestamp: "2026-01-01T00:00:00Z" }),
        event({ seq: 1, timestamp: "2026-01-01T00:01:23Z" }),
      ]),
    ).toBe(83_000);
    // An unparseable timestamp degrades to null (never a NaN duration).
    expect(runElapsedMs([event({ seq: 0, timestamp: "not-a-date" })])).toBeNull();
  });

  it("formats a duration compactly (s / m s / h m)", () => {
    expect(formatDuration(45_000)).toBe("45s");
    expect(formatDuration(83_000)).toBe("1m 23s");
    expect(formatDuration(120_000)).toBe("2m");
    expect(formatDuration(3_840_000)).toBe("1h 4m");
  });
});
