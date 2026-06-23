import type { RunProgressEvent } from "@/lib/api/types";

/**
 * Pure helpers for the live run view — the journey vocabulary and the grouping /
 * outcome derivations, kept out of the component so they're unit-testable. Mirrors
 * the backend emitter (ADR-0050): phases run/select/generate/execute/review,
 * statuses started/passed/failed/skipped, and the run-level terminal event.
 */

export const RUN_PHASE = "run";

const TERMINAL_STATUSES = new Set(["passed", "failed", "skipped"]);

/** The run-level completion event that closes the live stream (phase `run`). */
export function isTerminalEvent(event: RunProgressEvent): boolean {
  return event.phase === RUN_PHASE && TERMINAL_STATUSES.has(event.status);
}

export interface PhaseSpec {
  key: string;
  label: string;
  caption: string;
}

/** The visible progress spine, in journey order (understand → review). The framing
 *  `run` phase isn't a spine step — it drives the overall outcome banner. */
export const PHASE_SPINE: PhaseSpec[] = [
  { key: "select", label: "Understand", caption: "select what to test" },
  { key: "generate", label: "Generate", caption: "author the tests" },
  { key: "execute", label: "Execute", caption: "run the journeys" },
  { key: "review", label: "Review", caption: "rank the findings" },
];

export interface PhaseGroup {
  spec: PhaseSpec;
  events: RunProgressEvent[];
}

/**
 * Group events into the phase spine: the four known phases always appear (in spine
 * order, possibly empty so the journey ahead is visible), then any other non-`run`
 * phase the backend emits is appended in first-seen order (forward-compat, never
 * dropped). The `run` phase is excluded — it's the overall frame, not a step.
 */
export function groupByPhase(events: RunProgressEvent[]): PhaseGroup[] {
  const known = new Map(PHASE_SPINE.map((spec) => [spec.key, spec]));
  const order: string[] = PHASE_SPINE.map((spec) => spec.key);
  for (const event of events) {
    if (event.phase === RUN_PHASE) continue;
    if (!order.includes(event.phase)) order.push(event.phase);
  }
  return order.map((key) => ({
    spec: known.get(key) ?? { key, label: key, caption: "" },
    events: events.filter((event) => event.phase === key),
  }));
}

/** The run's final outcome from its last terminal event, or null if still running. */
export function runOutcome(
  events: RunProgressEvent[],
): "passed" | "failed" | "skipped" | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (isTerminalEvent(events[i])) {
      return events[i].status as "passed" | "failed" | "skipped";
    }
  }
  return null;
}

/**
 * The seq of the step that's currently running — the latest event when it's an
 * unclosed `started` and the run hasn't finished — so the view can highlight it.
 * Returns null once the run is terminal (nothing is live).
 */
export function currentStepSeq(events: RunProgressEvent[]): number | null {
  if (events.length === 0 || runOutcome(events) !== null) return null;
  const last = events[events.length - 1];
  return last.status === "started" ? last.seq : null;
}

/** Detail object → compact ["key", "value"] pairs (we render exactly what's there). */
export function detailEntries(
  detail: Record<string, unknown> | null | undefined,
): [string, string][] {
  if (!detail) return [];
  return Object.entries(detail).map(([key, value]) => [key, String(value)]);
}
