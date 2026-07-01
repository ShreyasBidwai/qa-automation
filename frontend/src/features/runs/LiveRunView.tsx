import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronDown,
  Globe,
  ImageOff,
  Loader2,
  Minus,
  RefreshCw,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { RunProgressEvent } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import {
  currentStepSeq,
  detailEntries,
  formatDuration,
  frameLabel,
  groupByPhase,
  latestScreenshotEvent,
  type PhaseGroup,
  runElapsedMs,
  runOutcome,
} from "./runEvents";
import { useRunEvents, type RunEventsConnection } from "./useRunEvents";
import { useRunScreenshot } from "./useRunScreenshot";

/**
 * The live run view — watch a run's journey happen step-by-step (ADR-0050),
 * rather than waiting for the final report. A vertical step list grouped by phase
 * (understand → generate → execute → review) forms a progress spine; each step
 * shows its label, a status icon (running → passed/failed/skipped), and any
 * detail. It renders live (SSE, with on-connect replay catch-up) for an
 * in-progress run AND from the replay alone for a finished run — the journey is
 * replayable, not just live. Failing steps are emphasised and auto-reveal their
 * screenshot (the bug — don't make them hunt); other steps reveal on click.
 */
export function LiveRunView({ runId }: { runId: string }) {
  const { events, connection, terminal, reconnect } = useRunEvents(runId);
  const groups = groupByPhase(events);
  const outcome = runOutcome(events);
  const currentSeq = currentStepSeq(events);
  const liveFrame = latestScreenshotEvent(events);
  const live = connection === "live" || connection === "connecting";

  return (
    <>
      <PageHeader
        eyebrow={<Link to={`/runs/${runId}`}>Run</Link>}
        title="Live run"
        description={<span className="font-mono">{runId}</span>}
        action={
          terminal ? (
            <Button asChild variant="outline" size="sm">
              <Link to={`/runs/${runId}/findings`}>View findings</Link>
            </Button>
          ) : undefined
        }
      />
      <main className="flex-1 px-6 py-8 lg:px-8">
        <div className="mx-auto max-w-[1200px]">
          <div className="mb-6">
            <Link
              to={`/runs/${runId}`}
              className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Run overview
            </Link>
          </div>

          {connection === "connecting" && events.length === 0 ? (
            <SkeletonRows label="Loading the run journey…" />
          ) : connection === "error" && events.length === 0 ? (
            <StatePanel
              icon={AlertTriangle}
              tone="danger"
              title="Couldn't load the run journey"
              description="Polaris couldn't reach the run-events stream. This is usually temporary."
              actions={
                <Button variant="primary" size="sm" onClick={reconnect}>
                  Reconnect
                </Button>
              }
            />
          ) : (
            <>
              <RunSummary
                connection={connection}
                outcome={outcome}
                events={events}
                groups={groups}
                currentSeq={currentSeq}
                onReconnect={reconnect}
              />
              {liveFrame ? (
                <LiveBrowserFrame runId={runId} event={liveFrame} live={live} />
              ) : null}
              <StepSpine groups={groups} currentSeq={currentSeq} runId={runId} />
            </>
          )}
        </div>
      </main>
    </>
  );
}

// --- run summary (status · elapsed · steps + the phase progress strip) -------

type SummaryTone = "accent" | "pass" | "fail" | "neutral";

const TONE_TEXT: Record<SummaryTone, string> = {
  accent: "text-foreground",
  pass: "text-status-pass-fg",
  fail: "text-status-fail-fg",
  neutral: "text-foreground",
};

const TONE_DOT: Record<SummaryTone, string> = {
  accent: "bg-accent",
  pass: "bg-status-pass-solid",
  fail: "bg-status-fail-solid",
  neutral: "bg-status-neutral-solid",
};

/** The run's headline: what's happening, for how long, how many steps — plus the
 *  phase progress strip beneath it. Replaces the flat status banner so a long
 *  generation reads as "Running · 2m · 34 steps" with a live phase readout. */
function RunSummary({
  connection,
  outcome,
  events,
  groups,
  currentSeq,
  onReconnect,
}: {
  connection: RunEventsConnection;
  outcome: "passed" | "failed" | "skipped" | null;
  events: RunProgressEvent[];
  groups: PhaseGroup[];
  currentSeq: number | null;
  onReconnect: () => void;
}) {
  const live = connection === "live" || connection === "connecting";
  const elapsed = runElapsedMs(events);
  const { label, tone }: { label: string; tone: SummaryTone } = live
    ? { label: "Running", tone: "accent" }
    : outcome === "failed"
      ? { label: "Run failed", tone: "fail" }
      : outcome === "passed"
        ? { label: "Run passed", tone: "pass" }
        : { label: "Run ended", tone: "neutral" };

  return (
    <section className="mb-6 overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className={cn(
              "h-2 w-2 rounded-full",
              TONE_DOT[tone],
              live && "motion-safe:animate-pulse",
            )}
          />
          <span className={cn("text-sm font-semibold", TONE_TEXT[tone])}>{label}</span>
          {live ? (
            <span className="text-[13px] text-muted-foreground">— watching live</span>
          ) : null}
          {elapsed !== null ? (
            <span className="text-[13px] tabular-nums text-muted-foreground">
              · {formatDuration(elapsed)}
            </span>
          ) : null}
          <span className="text-[13px] text-muted-foreground">
            · {events.length} {events.length === 1 ? "step" : "steps"}
          </span>
        </div>

        {/* The journey ended without a terminal event, or the stream dropped — let a
         *  long run resume rather than stranding the viewer on a partial journey. */}
        {connection === "done" && outcome === null ? (
          <Button variant="ghost" size="sm" onClick={onReconnect}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Resume
          </Button>
        ) : connection === "error" ? (
          <Button variant="ghost" size="sm" onClick={onReconnect}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Reconnect
          </Button>
        ) : null}
      </div>

      <PhaseStrip groups={groups} currentSeq={currentSeq} />
    </section>
  );
}

/** A compact left-to-right readout of the phase pipeline, each phase showing its
 *  state (done ✓ · running spinner · pending dot) and how many steps it holds. */
function PhaseStrip({
  groups,
  currentSeq,
}: {
  groups: PhaseGroup[];
  currentSeq: number | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-2 border-t border-border-subtle bg-background px-5 py-2.5">
      {groups.map((group, index) => (
        <div key={group.spec.key} className="flex items-center">
          {index > 0 ? (
            <span aria-hidden="true" className="px-1 text-marker">
              ›
            </span>
          ) : null}
          <PhaseChip group={group} state={phaseState(group, currentSeq)} />
        </div>
      ))}
    </div>
  );
}

function PhaseChip({ group, state }: { group: PhaseGroup; state: PhaseState }) {
  const count = group.events.length;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium",
        state === "failed"
          ? "bg-status-fail-bg text-status-fail-fg"
          : state === "running"
            ? "bg-accent-subtle text-accent"
            : state === "passed"
              ? "bg-status-pass-bg text-status-pass-fg"
              : "text-status-neutral-solid",
      )}
    >
      {state === "running" ? (
        <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden="true" />
      ) : state === "passed" ? (
        <Check className="h-3 w-3" aria-hidden="true" />
      ) : state === "failed" ? (
        <X className="h-3 w-3" aria-hidden="true" />
      ) : (
        <span
          aria-hidden="true"
          className="h-1.5 w-1.5 rounded-full border border-current"
        />
      )}
      {group.spec.label}
      {count > 0 ? <span className="tabular-nums opacity-70">{count}</span> : null}
    </span>
  );
}

// --- the phase spine ---------------------------------------------------------

function StepSpine({
  groups,
  currentSeq,
  runId,
}: {
  groups: PhaseGroup[];
  currentSeq: number | null;
  runId: string;
}) {
  return (
    // role="log" + aria-live: each newly-appended step is announced once, in order.
    <div
      role="log"
      aria-live="polite"
      aria-relevant="additions"
      aria-label="Run progress"
    >
      <ol className="space-y-6">
        {groups.map((group) => (
          <PhaseColumn
            key={group.spec.key}
            group={group}
            currentSeq={currentSeq}
            runId={runId}
          />
        ))}
      </ol>
    </div>
  );
}

type PhaseState = "pending" | "running" | "passed" | "failed";

function phaseState(group: PhaseGroup, currentSeq: number | null): PhaseState {
  if (group.events.length === 0) return "pending";
  if (group.events.some((event) => event.status === "failed")) return "failed";
  if (group.events.some((event) => event.seq === currentSeq)) return "running";
  return "passed";
}

// A phase with a long tail (e.g. generation over 50 targets) folds its older steps
// so the view stays scannable — the most recent + the active step always show.
const STEP_FOLD_LIMIT = 8;

function PhaseColumn({
  group,
  currentSeq,
  runId,
}: {
  group: PhaseGroup;
  currentSeq: number | null;
  runId: string;
}) {
  const state = phaseState(group, currentSeq);
  const pending = state === "pending";
  const [showAll, setShowAll] = useState(false);
  const total = group.events.length;
  const folded = !showAll && total > STEP_FOLD_LIMIT;
  const shown = folded ? group.events.slice(total - STEP_FOLD_LIMIT) : group.events;
  const hidden = total - shown.length;

  return (
    <li>
      <div className="mb-2.5 flex items-baseline gap-2">
        <h2
          className={cn(
            "text-[13px] font-semibold uppercase tracking-[0.05em]",
            pending ? "text-status-neutral-solid" : "text-foreground",
          )}
        >
          {group.spec.label}
        </h2>
        {group.spec.caption ? (
          <span className="text-[11.5px] text-status-neutral-solid">
            {group.spec.caption}
          </span>
        ) : null}
        {pending ? (
          <span className="text-[11.5px] italic text-status-neutral-solid">
            · up next
          </span>
        ) : total > 0 ? (
          <span className="text-[11.5px] tabular-nums text-status-neutral-solid">
            · {total} {total === 1 ? "step" : "steps"}
          </span>
        ) : null}
      </div>

      <div className="ml-1 border-l border-border-subtle pl-4">
        {total === 0 ? (
          <p className="py-1 text-[13px] text-muted-foreground">
            {pending
              ? "Waiting for the earlier phases to finish."
              : "Nothing to show here."}
          </p>
        ) : (
          <>
            {folded ? (
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className="mb-2 text-[12px] font-medium text-accent hover:underline"
              >
                Show {hidden} earlier {hidden === 1 ? "step" : "steps"}
              </button>
            ) : null}
            <ul className="space-y-2">
              {shown.map((event) => (
                <StepRow
                  key={event.seq}
                  event={event}
                  current={event.seq === currentSeq}
                  runId={runId}
                />
              ))}
            </ul>
          </>
        )}
      </div>
    </li>
  );
}

// --- one step row ------------------------------------------------------------

function StepRow({
  event,
  current,
  runId,
}: {
  event: RunProgressEvent;
  current: boolean;
  runId: string;
}) {
  const failed = event.status === "failed";
  const hasShot = event.has_screenshot === true;
  const [revealed, setRevealed] = useState(false);
  // A failing step that captured a screenshot auto-reveals it once (that's where the
  // bug is); the user can still collapse it, and it won't re-open on re-renders.
  const autoExpanded = useRef(false);
  useEffect(() => {
    if (failed && hasShot && !autoExpanded.current) {
      autoExpanded.current = true;
      setRevealed(true);
    }
  }, [failed, hasShot]);

  const entries = detailEntries(event.detail);
  return (
    <li
      className={cn(
        "rounded-[9px] border px-3 py-2.5 transition-colors",
        failed
          ? "border-status-fail-border bg-status-fail-bg/40"
          : current
            ? "border-accent/60 bg-accent-subtle"
            : "border-transparent",
      )}
    >
      <div className="flex items-start gap-2.5">
        <StepStatusIcon status={event.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span
              className={cn(
                "text-[13.5px] leading-snug",
                failed
                  ? "font-semibold text-status-fail-fg"
                  : "text-foreground-secondary",
              )}
            >
              {event.step}
            </span>
            {/* Status word travels with the icon (colour is never the only signal,
             *  and it gives the aria-live announcement its meaning). */}
            <span className="sr-only">{event.status}</span>
            <span className="font-mono text-[10.5px] text-status-neutral-solid">
              {clockTime(event.timestamp)}
            </span>
          </div>

          {entries.length > 0 ? (
            <dl className="mt-1.5 flex flex-wrap gap-1.5">
              {entries.map(([key, value]) => (
                <span
                  key={key}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-[5px] px-1.5 py-0.5 font-mono text-[10.5px]",
                    failed && (key === "expected" || key === "actual")
                      ? "bg-status-fail-bg text-status-fail-fg"
                      : "bg-status-neutral-bg text-status-neutral-fg",
                  )}
                >
                  <dt className="opacity-70">{key}</dt>
                  <dd>{value}</dd>
                </span>
              ))}
            </dl>
          ) : null}

          {hasShot ? (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setRevealed((value) => !value)}
                aria-expanded={revealed}
                className="inline-flex items-center gap-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                <ChevronDown
                  className={cn(
                    "h-3.5 w-3.5 transition-transform",
                    revealed && "rotate-180",
                  )}
                  aria-hidden="true"
                />
                {revealed ? "Hide screenshot" : "Show screenshot"}
              </button>
              {revealed ? <ScreenshotPanel runId={runId} seq={event.seq} /> : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function StepStatusIcon({ status }: { status: string }) {
  const base = "flex h-5 w-5 shrink-0 items-center justify-center rounded-full mt-0.5";
  if (status === "started") {
    return (
      <span className={cn(base, "text-accent")} aria-hidden="true">
        <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" />
      </span>
    );
  }
  if (status === "passed") {
    return (
      <span
        className={cn(base, "bg-status-pass-bg text-status-pass-fg")}
        aria-hidden="true"
      >
        <Check className="h-3 w-3" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className={cn(base, "bg-status-fail-bg text-status-fail-solid")}
        aria-hidden="true"
      >
        <X className="h-3 w-3" />
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className={cn(base, "text-status-neutral-solid")} aria-hidden="true">
        <Minus className="h-3.5 w-3.5" />
      </span>
    );
  }
  return (
    <span className={cn(base, "text-status-neutral-solid")} aria-hidden="true">
      <span className="h-1.5 w-1.5 rounded-full bg-status-neutral-solid" />
    </span>
  );
}

/**
 * The live "browser window" — the operator literally watches Polaris drive the
 * running app. It shows the most recent step that captured a screenshot, framed in
 * faux browser chrome (URL bar + a Live badge while the run streams). As the crawl
 * visits each page, `event` advances and the frame swaps, so it animates page by
 * page. The bytes come from the authorized per-seq endpoint via `useRunScreenshot`.
 */
function LiveBrowserFrame({
  runId,
  event,
  live,
}: {
  runId: string;
  event: RunProgressEvent;
  live: boolean;
}) {
  const { url, state } = useRunScreenshot(runId, event.seq, true);
  const label = frameLabel(event);
  return (
    <div className="mb-6 overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="flex items-center gap-2 border-b border-border bg-background px-3 py-2">
        <div className="flex gap-1.5" aria-hidden="true">
          <span className="h-2.5 w-2.5 rounded-full bg-status-fail-solid/60" />
          <span className="h-2.5 w-2.5 rounded-full bg-status-flaky-solid/60" />
          <span className="h-2.5 w-2.5 rounded-full bg-status-pass-solid/60" />
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1">
          <Globe
            className="h-3 w-3 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <span className="truncate font-mono text-[11px] text-muted-foreground">
            {label}
          </span>
        </div>
        {live ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent-subtle px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-accent">
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 rounded-full bg-accent motion-safe:animate-pulse"
            />
            Live
          </span>
        ) : null}
      </div>

      <div className="relative flex aspect-[16/10] items-center justify-center bg-background">
        {url ? (
          // Keep the current frame up even while the next one is loading (no blink);
          // a subtle fade eases the swap between pages.
          <img
            key={url}
            src={url}
            alt={`What Polaris saw at ${label}`}
            className="h-full w-full animate-fade-in object-contain"
          />
        ) : state === "error" ? (
          <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
            <ImageOff className="h-5 w-5" aria-hidden="true" />
            <p className="text-[12.5px]">This frame isn&rsquo;t available.</p>
          </div>
        ) : (
          <Loader2
            className="h-5 w-5 text-muted-foreground motion-safe:animate-spin"
            aria-hidden="true"
          />
        )}
      </div>

      <div className="border-t border-border px-3 py-2">
        <p className="truncate text-[12.5px] text-foreground-secondary">{event.step}</p>
      </div>
    </div>
  );
}

/**
 * Per-step screenshot, shown when a step reveals its frame. Reuses the authorized
 * per-seq endpoint via `useRunScreenshot` (only fetches while revealed). An honest
 * fallback covers the loading + unavailable cases (e.g. a decoupled runner wrote
 * the bytes on a filesystem the control plane can't reach — ADR-0051).
 */
function ScreenshotPanel({ runId, seq }: { runId: string; seq: number }) {
  const { url, state } = useRunScreenshot(runId, seq, true);
  if (state === "ready" && url) {
    return (
      <div className="mt-2 overflow-hidden rounded-[9px] border border-border bg-background">
        <img
          src={url}
          alt={`Screenshot for step #${seq}`}
          className="max-h-[420px] w-full object-contain"
        />
      </div>
    );
  }
  return (
    <div className="mt-2 flex items-center gap-2 rounded-[9px] border border-dashed border-border bg-background px-3 py-4 text-muted-foreground">
      {state === "error" ? (
        <>
          <ImageOff className="h-4 w-4" aria-hidden="true" />
          <p className="text-[12.5px]">
            Screenshot isn&rsquo;t available for this step.
          </p>
        </>
      ) : (
        <>
          <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
          <p className="text-[12.5px]">Loading screenshot…</p>
        </>
      )}
    </div>
  );
}

/** Local clock time for a step event (HH:MM:SS) — honest, locale-aware. */
function clockTime(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString();
}
