import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  FlaskConical,
  Loader2,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { projectApi } from "@/lib/api/client";
import type { TestCaseSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { useAuthoringJob, type AuthoringJobState } from "./useAuthoringJob";
import { useProjectTests } from "./useProjectTests";

/**
 * The generated-tests viewer (#Tests) — QA can finally SEE what Polaris wrote:
 * every current test case, the endpoint it targets, its facets (happy/negative,
 * oracle source), and the runnable Pest code, foldable per row. Read-only.
 */
export function ProjectTestsPage({ projectId }: { projectId: string }) {
  // A "Describe it" run lands here with ?authoring=<jobId>: poll that job and reload
  // the list when it succeeds, so the freshly-authored cases appear on their own.
  // ?run=<runId> scopes the list to just the cases that run exercised (ADR-0062).
  const [params] = useState(() => new URLSearchParams(window.location.search));
  const authoringJobId = params.get("authoring");
  const runId = params.get("run");
  const [reloadToken, setReloadToken] = useState(0);
  const authoring = useAuthoringJob(authoringJobId, () =>
    setReloadToken((token) => token + 1),
  );
  const { tests, total, loading, error } = useProjectTests(
    projectId,
    reloadToken,
    runId,
  );
  const [type, setType] = useState<string>("all");

  const types = useMemo(() => facetCounts(tests, (t) => t.type), [tests]);
  const shown = type === "all" ? tests : tests.filter((t) => t.type === type);

  return (
    <PageShell
      scroll={false}
      header={
        <>
          <Link
            to={`/projects/${projectId}`}
            className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Project
          </Link>

          <AuthoringBanner state={authoring} />

          <header className="mt-3 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-foreground">
                {runId ? "Tests from this run" : "Generated tests"}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {runId ? (
                  <>
                    Only the cases this run exercised.{" "}
                    <Link
                      to={`/projects/${projectId}/tests`}
                      className="text-accent hover:underline"
                    >
                      View all tests
                    </Link>
                  </>
                ) : (
                  "The runnable tests Polaris authored from the model — target, kind, and the actual code."
                )}
              </p>
            </div>
            {!loading && !error ? (
              <span className="text-[13px] text-muted-foreground">
                {total} {total === 1 ? "test" : "tests"}
              </span>
            ) : null}
          </header>
        </>
      }
    >
      {loading ? (
        <div className="space-y-2.5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[52px] rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load the tests"
          description={error}
          actions={
            <Button asChild>
              <Link to={`/projects/${projectId}`}>Back to project</Link>
            </Button>
          }
        />
      ) : total === 0 ? (
        <StatePanel
          icon={FlaskConical}
          tone="neutral"
          title="No tests yet"
          description="Build the model, then start a run — Polaris generates tests from the model and they'll show up here."
          actions={
            <Button asChild>
              <Link to={`/projects/${projectId}/run`}>Start a run</Link>
            </Button>
          }
        />
      ) : (
        <>
          {/* Facet filter — kept simple: filter by kind (happy/negative/…). */}
          <div className="mb-4 flex flex-wrap items-center gap-1.5">
            <FilterChip
              label="All"
              count={total}
              active={type === "all"}
              onClick={() => setType("all")}
            />
            {types.map(([value, count]) => (
              <FilterChip
                key={value}
                label={titleCase(value)}
                count={count}
                active={type === value}
                onClick={() => setType(value)}
              />
            ))}
          </div>

          {/* The test list is the overflow — it scrolls internally (ADR-0066). */}
          <ul className="min-h-0 flex-1 space-y-2.5 overflow-y-auto pb-1 pr-0.5">
            {shown.map((test) => (
              <TestRow
                key={test.id}
                test={test}
                projectId={projectId}
                onReviewed={() => setReloadToken((token) => token + 1)}
              />
            ))}
          </ul>
        </>
      )}
    </PageShell>
  );
}

/** Progress for a "Describe it" authoring job: a live "authoring…" state while the
 *  worker composes the tests, then a success/failure note (the list reloads on its
 *  own). Renders nothing when the page wasn't opened from an authoring run. */
function AuthoringBanner({ state }: { state: AuthoringJobState }) {
  if (state.active) {
    return (
      <div className="mt-3 flex items-center gap-2.5 rounded-lg border border-accent bg-accent-subtle px-4 py-3 text-sm text-accent">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
        Authoring tests from your description… they’ll appear here when ready.
      </div>
    );
  }
  if (state.outcome === "succeeded") {
    return (
      <div className="mt-3 rounded-lg border border-status-pass-border bg-status-pass-bg px-4 py-3 text-sm text-status-pass-fg">
        Tests authored — review the new proposals below.
      </div>
    );
  }
  if (state.outcome === "failed" || state.outcome === "cancelled") {
    return (
      <div className="mt-3 rounded-lg border border-status-fail-border bg-status-fail-bg px-4 py-3 text-sm text-status-fail-fg">
        {state.outcome === "failed" ? "Authoring failed" : "Authoring was cancelled"}
        {state.detail ? ` — ${state.detail}` : "."} Try rephrasing, or make sure the app
        has been ingested.
      </div>
    );
  }
  return null;
}

function TestRow({
  test,
  projectId,
  onReviewed,
}: {
  test: TestCaseSummary;
  projectId: string;
  onReviewed: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = test.proposal_status === "pending";

  async function review(action: "accept" | "discard") {
    setBusy(true);
    setError(null);
    const result =
      action === "accept"
        ? await projectApi.acceptTest(projectId, test.id)
        : await projectApi.discardTest(projectId, test.id);
    if (result.ok) {
      onReviewed(); // reloads the list — accepted stays, discarded drops out
      return;
    }
    setBusy(false);
    setError(result.error ?? "Couldn't update the test.");
  }

  return (
    <li
      className={cn(
        "overflow-hidden rounded-xl border bg-surface shadow-card",
        pending ? "border-status-flaky-fg" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
      >
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-medium text-foreground">
          {test.target}
        </span>
        {pending ? (
          <span className="shrink-0 rounded-full bg-status-flaky-bg px-2 py-0.5 text-[11px] font-medium text-status-flaky-fg">
            Proposed
          </span>
        ) : null}
        <TypeBadge type={test.type} />
        <span className="hidden font-mono text-[11px] text-status-neutral-solid sm:inline">
          {test.oracle_source}
        </span>
        <span className="hidden rounded-[5px] border border-border bg-status-neutral-bg px-1.5 py-0.5 font-mono text-[10.5px] text-status-neutral-fg md:inline">
          {test.framework}
        </span>
      </button>

      {pending ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border-subtle bg-background px-5 py-2.5">
          <span className="mr-auto text-xs text-muted-foreground">
            Authored from a description — accept to run it, or discard.
          </span>
          {error ? (
            <span role="alert" className="text-xs text-status-fail-fg">
              {error}
            </span>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void review("discard")}
          >
            Discard
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void review("accept")}>
            {busy ? "Saving…" : "Accept"}
          </Button>
        </div>
      ) : null}

      {open ? (
        <div className="border-t border-border-subtle bg-background">
          <pre className="max-h-[440px] overflow-auto px-5 py-4 font-mono text-[12.5px] leading-relaxed text-foreground-secondary">
            <code>{test.code || "// (no code generated for this case yet)"}</code>
          </pre>
        </div>
      ) : null}
    </li>
  );
}

/** Kind badge — a negative (failure-path) test stands apart from a happy one. */
function TypeBadge({ type }: { type: string }) {
  const negative = type === "negative";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
        negative
          ? "bg-status-flaky-bg text-status-flaky-fg"
          : "bg-status-pass-bg text-status-pass-fg",
      )}
    >
      {titleCase(type)}
    </span>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-3 py-1 text-[12.5px] font-medium transition-colors",
        active
          ? "border-accent bg-accent-subtle text-accent"
          : "border-border text-muted-foreground hover:bg-background hover:text-foreground",
      )}
    >
      {label} <span className="tabular-nums opacity-70">{count}</span>
    </button>
  );
}

/** Count of each facet value, in descending count order (for the filter chips). */
function facetCounts(
  tests: TestCaseSummary[],
  pick: (t: TestCaseSummary) => string,
): [string, number][] {
  const counts = new Map<string, number>();
  for (const test of tests) counts.set(pick(test), (counts.get(pick(test)) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function titleCase(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value;
}
