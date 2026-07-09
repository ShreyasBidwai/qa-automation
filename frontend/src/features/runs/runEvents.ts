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
  { key: "crawl", label: "Explore live site", caption: "drive the running app" },
  { key: "review", label: "Review", caption: "rank the findings" },
];

export interface PhaseGroup {
  spec: PhaseSpec;
  events: RunProgressEvent[];
}

/**
 * Collapse a step's lifecycle into ONE row. The backend emits a `started` event
 * and then a terminal (`passed`/`failed`/`skipped`) event for the same step — the
 * live view should show a single row that transitions spinner → check, not two
 * near-identical rows. We key by step label, keep the latest event (so the row
 * shows the current status), and preserve first-seen order (so a row never jumps
 * when it completes). A still-running step has only its `started` event → spinner.
 */
export function collapseSteps(events: RunProgressEvent[]): RunProgressEvent[] {
  const firstSeq = new Map<string, number>();
  const latest = new Map<string, RunProgressEvent>();
  for (const event of events) {
    if (!firstSeq.has(event.step)) firstSeq.set(event.step, event.seq);
    const prev = latest.get(event.step);
    if (!prev || event.seq >= prev.seq) latest.set(event.step, event);
  }
  return [...latest.values()].sort(
    (a, b) => (firstSeq.get(a.step) ?? a.seq) - (firstSeq.get(b.step) ?? b.seq),
  );
}

// The crawl ("Explore live site") phase only happens when a run tests the UI layer.
// An api-only run never crawls, so the phase must NOT show as an empty, misleading
// step in its timeline — it appears only once the run actually explores the live site
// (has ≥1 crawl event). Every other spine phase always appears.
const UI_ONLY_PHASES = new Set(["crawl"]);

/**
 * Group events into the phase spine: the always-present phases appear in spine order
 * (possibly empty, so the journey ahead is visible); a UI-only phase (crawl) appears
 * only when the run produced its events (see `UI_ONLY_PHASES`); then any other non-`run`
 * phase the backend emits is appended in first-seen order (forward-compat, never
 * dropped). The `run` phase is excluded — it's the overall frame, not a step.
 */
export function groupByPhase(events: RunProgressEvent[]): PhaseGroup[] {
  const known = new Map(PHASE_SPINE.map((spec) => [spec.key, spec]));
  const present = new Set(
    events.filter((event) => event.phase !== RUN_PHASE).map((e) => e.phase),
  );
  const order: string[] = PHASE_SPINE.filter(
    (spec) => !UI_ONLY_PHASES.has(spec.key) || present.has(spec.key),
  ).map((spec) => spec.key);
  for (const event of events) {
    if (event.phase === RUN_PHASE) continue;
    if (!order.includes(event.phase)) order.push(event.phase);
  }
  return order.map((key) => ({
    spec: known.get(key) ?? { key, label: key, caption: "" },
    events: collapseSteps(events.filter((event) => event.phase === key)),
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

/**
 * The most recent event that has a screenshot — the frame the live "browser
 * window" shows. As the crawl streams in, this advances to each new page, so the
 * top frame animates page-by-page; null when nothing visual has been captured yet.
 */
export function latestScreenshotEvent(
  events: RunProgressEvent[],
): RunProgressEvent | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i].has_screenshot) return events[i];
  }
  return null;
}

/** What a frame is showing: the crawled page URL (detail.url) or the step label. */
export function frameLabel(event: RunProgressEvent): string {
  const url = event.detail?.url;
  return typeof url === "string" && url ? url : event.step;
}

/**
 * Wall time the run has spanned so far — first event → last event, in ms. It grows
 * as events stream in (a live "elapsed"), and freezes at the terminal event. Null
 * when there's nothing to measure yet or a timestamp is unparseable. Pure: derived
 * from the events, never `Date.now()`, so it's deterministic + testable.
 */
export function runElapsedMs(events: RunProgressEvent[]): number | null {
  if (events.length === 0) return null;
  const first = Date.parse(events[0].timestamp);
  const last = Date.parse(events[events.length - 1].timestamp);
  if (Number.isNaN(first) || Number.isNaN(last)) return null;
  return Math.max(0, last - first);
}

/** Compact human duration for the run summary: "45s", "1m 23s", "1h 4m". */
export function formatDuration(ms: number): string {
  const total = Math.round(ms / 1000);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) {
    const seconds = total % 60;
    return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`;
}
