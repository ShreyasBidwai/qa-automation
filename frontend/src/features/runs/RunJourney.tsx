import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  FlaskConical,
  Globe,
  ImageOff,
  Loader2,
  Minus,
  RefreshCw,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Link } from "@/components/Link";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { RunProgressEvent } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { useProject } from "../projects/useProject";
import { useProjectTests } from "../projects/useProjectTests";
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
import { useRunStatus } from "./useRunStatus";

/**
 * The run journey — one focused view of a run, ONE phase at a time (ADR-0060).
 * The phase pipeline (Understand → Generate → Execute → Explore → Review) is a tab
 * strip; the body shows only the selected phase's content, so the operator watches
 * the current step of a live run without an ever-growing scroll. Tabs auto-follow the
 * active phase until the operator clicks one (then their choice sticks). The Generate
 * phase surfaces the tests it authored, each openable in a "View test" drawer.
 *
 * Reused by the Ongoing-run page (the live run) and `/runs/{id}/live` (replay of a
 * finished run) — identical, since a finished run replays from the same event stream.
 */
export function RunJourney({ runId }: { runId: string }) {
  const { events, connection, terminal, reconnect } = useRunEvents(runId);
  const { projectId } = useRunStatus(runId);
  const groups = groupByPhase(events);
  const outcome = runOutcome(events);
  const currentSeq = currentStepSeq(events);
  const liveFrame = latestScreenshotEvent(events);
  const live = connection === "live" || connection === "connecting";

  // Tabs auto-follow the active phase; a manual click pins the operator's choice.
  const activeKey = activePhaseKey(groups, currentSeq);
  const [manualKey, setManualKey] = useState<string | null>(null);
  const selectedKey = manualKey ?? activeKey;
  const selectedGroup =
    groups.find((group) => group.spec.key === selectedKey) ?? groups[0];

  if (connection === "connecting" && events.length === 0) {
    return <SkeletonRows label="Loading the run journey…" />;
  }
  if (connection === "error" && events.length === 0) {
    return (
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
    );
  }

  return (
    <div className="space-y-5">
      {projectId ? <RunProjectHeading projectId={projectId} /> : null}
      <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
        <RunSummaryRow
          runId={runId}
          connection={connection}
          outcome={outcome}
          events={events}
          terminal={terminal}
          onReconnect={reconnect}
        />
        <PhaseTabs
          groups={groups}
          currentSeq={currentSeq}
          selectedKey={selectedKey}
          onSelect={setManualKey}
        />
      </section>

      <PhaseBody
        group={selectedGroup}
        currentSeq={currentSeq}
        runId={runId}
        projectId={projectId}
        liveFrame={selectedKey === "crawl" ? liveFrame : null}
        live={live}
        terminal={terminal}
      />
    </div>
  );
}

/** The project this run belongs to, shown at the top of the journey (and linking
 *  back to it) so the operator always knows which app is under test. */
function RunProjectHeading({ projectId }: { projectId: string }) {
  const { project } = useProject(projectId);
  if (!project) return null;
  return (
    <Link
      to={`/projects/${projectId}`}
      className="inline-flex items-baseline gap-2 text-muted-foreground transition-colors hover:text-foreground"
    >
      <span className="text-[11px] font-semibold uppercase tracking-[0.06em]">
        Project
      </span>
      <span className="text-[17px] font-semibold tracking-[-0.01em] text-foreground">
        {project.name}
      </span>
    </Link>
  );
}

// --- summary row (status · elapsed · steps · reconnect) ----------------------

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

function RunSummaryRow({
  runId,
  connection,
  outcome,
  events,
  terminal,
  onReconnect,
}: {
  runId: string;
  connection: RunEventsConnection;
  outcome: "passed" | "failed" | "skipped" | null;
  events: RunProgressEvent[];
  terminal: boolean;
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

      <div className="flex items-center gap-1.5">
        {terminal ? (
          <Button asChild variant="outline" size="sm">
            <Link to={`/runs/${runId}/findings`}>View findings</Link>
          </Button>
        ) : null}
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
    </div>
  );
}

// --- the phase tab strip -----------------------------------------------------

type PhaseState = "pending" | "running" | "passed" | "failed";

function phaseState(group: PhaseGroup, currentSeq: number | null): PhaseState {
  if (group.events.length === 0) return "pending";
  if (group.events.some((event) => event.status === "failed")) return "failed";
  if (group.events.some((event) => event.seq === currentSeq)) return "running";
  return "passed";
}

/** The phase holding the current step (live), else the last phase with any events
 *  (where a finished run ended), else the first phase. Drives the default tab. */
function activePhaseKey(groups: PhaseGroup[], currentSeq: number | null): string {
  if (currentSeq !== null) {
    const running = groups.find((group) =>
      group.events.some((event) => event.seq === currentSeq),
    );
    if (running) return running.spec.key;
  }
  const lastWithEvents = [...groups].reverse().find((group) => group.events.length > 0);
  return lastWithEvents?.spec.key ?? groups[0]?.spec.key ?? "select";
}

function PhaseTabs({
  groups,
  currentSeq,
  selectedKey,
  onSelect,
}: {
  groups: PhaseGroup[];
  currentSeq: number | null;
  selectedKey: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Run phases"
      className="flex flex-wrap items-center gap-x-1 gap-y-2 border-t border-border-subtle bg-background px-3 py-2.5"
    >
      {groups.map((group, index) => (
        <div key={group.spec.key} className="flex items-center">
          {index > 0 ? (
            <span aria-hidden="true" className="px-0.5 text-marker">
              ›
            </span>
          ) : null}
          <PhaseTab
            group={group}
            state={phaseState(group, currentSeq)}
            selected={group.spec.key === selectedKey}
            onSelect={() => onSelect(group.spec.key)}
          />
        </div>
      ))}
    </div>
  );
}

function PhaseTab({
  group,
  state,
  selected,
  onSelect,
}: {
  group: PhaseGroup;
  state: PhaseState;
  selected: boolean;
  onSelect: () => void;
}) {
  const count = group.events.length;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        selected
          ? "bg-accent-subtle text-accent ring-1 ring-accent/40"
          : state === "failed"
            ? "text-status-fail-fg hover:bg-status-fail-bg"
            : state === "running"
              ? "text-accent hover:bg-accent-subtle"
              : state === "passed"
                ? "text-status-pass-fg hover:bg-status-pass-bg"
                : "text-status-neutral-solid hover:bg-surface",
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
    </button>
  );
}

// --- the single-phase body (tabpanel) ----------------------------------------

function PhaseBody({
  group,
  currentSeq,
  runId,
  projectId,
  liveFrame,
  live,
  terminal,
}: {
  group: PhaseGroup;
  currentSeq: number | null;
  runId: string;
  projectId: string | null;
  liveFrame: RunProgressEvent | null;
  live: boolean;
  terminal: boolean;
}) {
  const pending = group.events.length === 0;
  const isGenerate = group.spec.key === "generate";

  return (
    <section role="tabpanel" aria-label={group.spec.label} className="space-y-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
          {group.spec.label}
        </h2>
        {group.spec.caption ? (
          <span className="text-[12.5px] text-muted-foreground">
            {group.spec.caption}
          </span>
        ) : null}
        {group.events.length > 0 ? (
          <span className="text-[12px] tabular-nums text-status-neutral-solid">
            · {group.events.length} {group.events.length === 1 ? "step" : "steps"}
          </span>
        ) : null}
      </div>

      {/* Generate: one link through to the full generated-tests page. */}
      {isGenerate && projectId ? (
        <GeneratedTestsCTA projectId={projectId} runId={runId} />
      ) : null}

      {/* Explore/Execute: the live browser window as Polaris drives the app. */}
      {liveFrame ? (
        <LiveBrowserFrame runId={runId} event={liveFrame} live={live} />
      ) : null}

      {pending ? (
        <p className="rounded-lg border border-dashed border-border bg-surface px-4 py-6 text-center text-[13px] text-muted-foreground">
          {terminal
            ? "Nothing happened in this phase."
            : "Waiting for the earlier phases to finish."}
        </p>
      ) : (
        <div className="rounded-xl border border-border bg-surface shadow-card">
          {isGenerate ? (
            <p className="border-b border-border-subtle px-4 py-2 text-[12px] font-medium uppercase tracking-[0.05em] text-status-neutral-solid">
              Generation steps
            </p>
          ) : null}
          {/* Only ONE phase's steps show — the page's single scroll handles length,
              so there's no nested scroller and no cross-phase scrolling. */}
          <ul className="space-y-1.5 p-3">
            {group.events.map((event) => (
              <StepRow
                key={event.seq}
                event={event}
                current={event.seq === currentSeq}
                runId={runId}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// --- generated tests call-to-action -----------------------------------------

/** One link through to the generated-tests page, scoped to THIS run's cases
 *  (ADR-0062) — the tests a run authored are reviewed there (code, accept/discard),
 *  not in a per-test popup here. */
function GeneratedTestsCTA({ projectId, runId }: { projectId: string; runId: string }) {
  const { total, loading } = useProjectTests(projectId, 0, runId);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3.5 shadow-card">
      <div className="flex items-center gap-2.5">
        <FlaskConical
          className="h-4 w-4 shrink-0 text-status-neutral-solid"
          aria-hidden="true"
        />
        <p className="text-[13.5px] text-foreground-secondary">
          {loading
            ? "Loading this run's tests…"
            : total === 0
              ? "No tests authored yet."
              : `Polaris authored ${total} ${total === 1 ? "test" : "tests"} in this run.`}
        </p>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link to={`/projects/${projectId}/tests?run=${runId}`}>
          View this run's tests
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </Button>
    </div>
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

// --- live browser frame + per-step screenshot --------------------------------

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
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
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
