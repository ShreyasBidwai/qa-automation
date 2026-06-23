import { describe, expect, it } from "vitest";

import type { RunProgressEvent } from "@/lib/api/types";

import {
  currentStepSeq,
  detailEntries,
  groupByPhase,
  isTerminalEvent,
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

  it("groups into the spine (all four phases, run excluded, unknown appended)", () => {
    const groups = groupByPhase([
      event({ seq: 0, phase: "run", step: "run", status: "started" }),
      event({ seq: 1, phase: "generate", step: "gen" }),
      event({ seq: 2, phase: "deploy", step: "ship" }), // unknown phase
    ]);
    const keys = groups.map((g) => g.spec.key);
    // The four spine phases always appear in order, then the unknown one; `run` is
    // never a group.
    expect(keys).toEqual(["select", "generate", "execute", "review", "deploy"]);
    expect(groups.find((g) => g.spec.key === "generate")?.events).toHaveLength(1);
    expect(groups.find((g) => g.spec.key === "select")?.events).toHaveLength(0);
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
});
