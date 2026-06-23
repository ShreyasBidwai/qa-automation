import {
  AlertTriangle,
  ArrowLeft,
  Camera,
  Check,
  ChevronDown,
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
  groupByPhase,
  type PhaseGroup,
  runOutcome,
} from "./runEvents";
import { useRunEvents, type RunEventsConnection } from "./useRunEvents";

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
      <main className="flex-1 px-6 py-8">
        <div className="mx-auto max-w-[820px]">
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
              <ConnectionBanner
                connection={connection}
                outcome={outcome}
                stepCount={events.length}
                onReconnect={reconnect}
              />
              <StepSpine groups={groups} currentSeq={currentSeq} runId={runId} />
            </>
          )}
        </div>
      </main>
    </>
  );
}

// --- overall status banner ---------------------------------------------------

function ConnectionBanner({
  connection,
  outcome,
  stepCount,
  onReconnect,
}: {
  connection: RunEventsConnection;
  outcome: "passed" | "failed" | "skipped" | null;
  stepCount: number;
  onReconnect: () => void;
}) {
  const live = connection === "live" || connection === "connecting";
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3">
      <div className="flex items-center gap-2.5">
        {live ? (
          <>
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full bg-accent motion-safe:animate-pulse"
            />
            <span className="text-sm font-medium text-foreground">
              Running — watching live
            </span>
          </>
        ) : outcome === "failed" ? (
          <>
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full bg-status-fail-solid"
            />
            <span className="text-sm font-medium text-status-fail-fg">Run failed</span>
          </>
        ) : outcome === "passed" ? (
          <>
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full bg-status-pass-solid"
            />
            <span className="text-sm font-medium text-status-pass-fg">Run passed</span>
          </>
        ) : (
          <>
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full bg-status-neutral-solid"
            />
            <span className="text-sm font-medium text-foreground">Run ended</span>
          </>
        )}
        <span className="text-[13px] text-muted-foreground">
          · {stepCount} {stepCount === 1 ? "step" : "steps"}
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
            · waiting
          </span>
        ) : null}
      </div>

      <div className="ml-1 border-l border-border-subtle pl-4">
        {group.events.length === 0 ? (
          <p className="py-1 text-[13px] text-muted-foreground">
            No steps in this phase yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {group.events.map((event) => (
              <StepRow
                key={event.seq}
                event={event}
                current={event.seq === currentSeq}
                runId={runId}
              />
            ))}
          </ul>
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
  const [revealed, setRevealed] = useState(false);
  // A failing step auto-reveals its screenshot once (that's where the bug is);
  // the user can still collapse it, and it won't re-open on later re-renders.
  const autoExpanded = useRef(false);
  useEffect(() => {
    if (failed && !autoExpanded.current) {
      autoExpanded.current = true;
      setRevealed(true);
    }
  }, [failed]);

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
 * Per-step screenshot. The capture source (has_screenshot + the screenshot
 * endpoint, or a per-step shot) lands in a sibling backend slice and isn't on
 * trunk yet, so we show a clean, honest placeholder on reveal rather than a broken
 * image. When the field/endpoint arrives, swap the placeholder for the <img>.
 */
function ScreenshotPanel({ runId, seq }: { runId: string; seq: number }) {
  return (
    <div className="mt-2 rounded-[9px] border border-dashed border-border bg-background px-3 py-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Camera className="h-4 w-4" aria-hidden="true" />
        <p className="text-[12.5px]">
          Screenshot capture isn&rsquo;t available for this step yet.
        </p>
      </div>
      <p className="mt-1 font-mono text-[10.5px] text-status-neutral-solid">
        run {runId.slice(0, 8)} · step #{seq}
      </p>
    </div>
  );
}

/** Local clock time for a step event (HH:MM:SS) — honest, locale-aware. */
function clockTime(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString();
}
