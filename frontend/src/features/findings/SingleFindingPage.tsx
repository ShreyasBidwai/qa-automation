import { AlertTriangle, ArrowLeft, Inbox, MousePointerClick } from "lucide-react";
import type { ReactNode } from "react";

import { Link } from "@/components/Link";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TrustMark } from "@/components/ui/TrustMark";
import type { EvidenceItem, Finding } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { BlastPathRibbon } from "../runs/BlastPathRibbon";
import { triageSpec } from "../runs/findingBadges";
import {
  confidenceRationale,
  failureLine,
  findingRationale,
  parseRootCauseKey,
  parseSignature,
  statusMeaning,
} from "../runs/findingDetail";
import { historyViz, severityViz } from "../runs/findingViz";
import { useFinding } from "./useFinding";

/**
 * The dedicated single-finding screen (#findings/{id}) — one finding as a
 * complete, structured bug report on its own full-screen route, for QA who want
 * the whole picture rather than the master-detail side panel. It renders ONLY
 * what the finding actually carries: each required bug-report field is bound to
 * real data, and anything the payload genuinely lacks is omitted or marked "not
 * captured" — never invented. Reuses the shared primitives (TrustMark, the
 * BlastPathRibbon, the severity/history/triage maps) so it reads identically to
 * the detail panel. There is no GET /findings/{id} yet, so the finding is loaded
 * via {@link useFinding} (run-scoped when `?run=` is present, else the open inbox).
 */
export function SingleFindingPage({ findingId }: { findingId: string }) {
  // The inbox row and dashboard detail link with `?run=`, so the fetch is exact;
  // a cold deep link falls back to the open set. Read at render — navigation
  // re-renders the app, so the value is current.
  const runId = new URLSearchParams(window.location.search).get("run");
  const { finding, loading, error, notFound } = useFinding(findingId, runId);

  return (
    <div className="mx-auto max-w-[900px] px-6 py-8">
      <Link
        to="/findings"
        className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Findings
      </Link>

      {loading ? (
        <div className="mt-6">
          <SkeletonRows label="Loading finding…" />
        </div>
      ) : error ? (
        <div className="mt-10 flex justify-center">
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load this finding"
            description="Polaris couldn't reach the findings service. This is usually temporary."
            code={error}
            actions={
              <Button
                variant="primary"
                size="sm"
                onClick={() => window.location.reload()}
              >
                Retry
              </Button>
            }
          />
        </div>
      ) : !finding ? (
        <div className="mt-10 flex justify-center">
          <StatePanel
            icon={notFound ? MousePointerClick : Inbox}
            title="This finding isn't available here"
            description={
              runId
                ? "It isn't among this run's findings — it may have been removed."
                : "It isn't in the currently-open set across your projects. Open it from a run to see a resolved or superseded finding."
            }
            actions={
              <Link
                to="/findings"
                className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground hover:bg-background"
              >
                Back to inbox
              </Link>
            }
          />
        </div>
      ) : (
        <Report finding={finding} />
      )}
    </div>
  );
}

function Report({ finding }: { finding: Finding }) {
  const severity = severityViz(finding.severity);
  const summary = failureLine(finding);
  const parsed = parseRootCauseKey(finding.root_cause_key);
  const signature = parseSignature(parsed.signature);
  const expectedStatus = readExpectedStatus(finding.expected);
  const hasExpectedVsActual = Boolean(
    expectedStatus || signature.status || signature.outcome,
  );

  return (
    <article className="mt-4">
      {/* Title + the navigational context (project / run), when present. */}
      <header className="border-b border-border-subtle pb-5">
        <h1 className="text-[24px] font-semibold leading-[1.25] tracking-[-0.015em] text-foreground">
          {finding.title}
        </h1>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-muted-foreground">
          {finding.run_id ? (
            <Link
              to={`/runs/${finding.run_id}/findings`}
              className="font-medium text-accent hover:underline"
            >
              View run
            </Link>
          ) : null}
          {finding.project_id ? (
            <Link
              to={`/projects/${finding.project_id}`}
              className="font-medium text-accent hover:underline"
            >
              View project
            </Link>
          ) : null}
          <span>
            Explains {finding.explains_count}{" "}
            {finding.explains_count === 1 ? "test" : "tests"}
          </span>
        </div>
      </header>

      {/* Severity, Status and Trust are three DIFFERENT axes — shown separately,
       *  each labelled, each in its own visual language so they never blur. */}
      <div className="mt-5 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border-subtle bg-border-subtle sm:grid-cols-3">
        <MetaCell label="Severity" hint="technical impact">
          <span
            className={cn(
              "inline-block rounded px-2 py-0.5 text-[12px] font-semibold tracking-[0.02em]",
              severity.pill,
            )}
          >
            {severity.label}
          </span>
        </MetaCell>
        <MetaCell label="Status" hint="triage disposition">
          <Badge level={triageSpec(finding.triage?.status ?? "open").level}>
            {triageSpec(finding.triage?.status ?? "open").label}
          </Badge>
        </MetaCell>
        <MetaCell label="Trust" hint="how much to believe it">
          <TrustMark source={finding.oracle_source} label />
        </MetaCell>
      </div>

      {/* The three axes above, married into ONE verdict — what to do at a glance. */}
      <p className="mt-3 rounded-lg border border-border-subtle bg-background px-3.5 py-2.5 text-[13px] font-medium text-foreground-secondary">
        {findingRationale(finding)}
      </p>

      <Section title="What's wrong">
        {summary ? (
          <p className="text-[14px] leading-[1.55] text-foreground-secondary">
            {summary}.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            No machine-readable failure summary is encoded for this finding — see the
            evidence below for the failing assertions.
          </p>
        )}
        <p className="mt-2 text-[13px] leading-[1.5] text-muted-foreground">
          {confidenceRationale(finding.oracle_source)}
        </p>
      </Section>

      {/* Steps to reproduce aren't captured on any finding payload today; we say
       *  so plainly rather than invent a sequence. */}
      <Section title="Steps to reproduce">
        <p className="text-sm text-muted-foreground">
          Reproduction steps aren&rsquo;t captured for this finding.
        </p>
      </Section>

      {hasExpectedVsActual ? (
        <Section title="Expected vs actual">
          <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border-subtle bg-border-subtle sm:grid-cols-2">
            <ExpectedActualCell label="Expected">
              {expectedStatus ? (
                <span className="font-mono text-[13px] text-foreground">
                  HTTP {expectedStatus}
                </span>
              ) : (
                <span className="text-[13px] text-muted-foreground">Not captured</span>
              )}
            </ExpectedActualCell>
            <ExpectedActualCell label="Actual">
              {signature.status ? (
                <span className="font-mono text-[13px] text-status-fail-fg">
                  HTTP {signature.status}
                </span>
              ) : signature.outcome ? (
                <span className="font-mono text-[13px] text-status-fail-fg">
                  {signature.outcome}
                </span>
              ) : (
                <span className="text-[13px] text-muted-foreground">—</span>
              )}
            </ExpectedActualCell>
          </dl>
        </Section>
      ) : null}

      <Section title="Layer & blast path">
        <div className="mb-3.5 flex flex-wrap items-center gap-2 text-[13px]">
          <span className="text-status-neutral-solid">Layer</span>
          <span className="rounded-[5px] bg-status-neutral-bg px-2 py-0.5 font-mono text-xs text-status-neutral-fg">
            {finding.layer}
          </span>
        </div>
        <BlastPathRibbon finding={finding} />
      </Section>

      <Section title="For developers">
        <dl className="space-y-3 text-[13px]">
          {parsed.anchorKind !== "none" ? (
            <DevRow label="Failing node">
              <span className="font-mono text-status-fail-fg">
                {parsed.anchorValue}
              </span>{" "}
              <span className="text-muted-foreground">({parsed.anchorKind})</span>
            </DevRow>
          ) : null}
          {finding.location?.anchor?.label ? (
            <DevRow label="Anchor">
              <span className="font-mono text-foreground-secondary">
                {finding.location.anchor.label}
              </span>
            </DevRow>
          ) : null}
          <DevRow label="Root cause key">
            <code className="break-all font-mono text-xs text-foreground-secondary">
              {finding.root_cause_key}
            </code>
          </DevRow>
        </dl>
      </Section>

      <Section title="Evidence">
        <EvidenceBlock
          evidence={finding.evidence ?? null}
          reference={finding.evidence_ref ?? null}
        />
      </Section>

      <Section title="History">
        <HistoryBlock finding={finding} />
      </Section>

      <Section title="Linked tests">
        <p className="text-[13px] text-foreground-secondary">
          Explains {finding.explains_count}{" "}
          {finding.explains_count === 1 ? "test" : "tests"}.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          The individual test identities aren&rsquo;t carried on the finding payload —
          open the run to see the tests it groups.
        </p>
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-border-subtle py-5 last:border-b-0">
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-status-neutral-solid">
        {title}
      </h2>
      {children}
    </section>
  );
}

function MetaCell({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-surface px-4 py-3.5">
      <div className="flex items-baseline gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
          {label}
        </span>
        <span className="text-[10.5px] text-status-neutral-solid">{hint}</span>
      </div>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function ExpectedActualCell({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-surface px-3.5 py-3">
      <dt className="text-[11px] font-medium uppercase tracking-[0.04em] text-status-neutral-solid">
        {label}
      </dt>
      <dd className="mt-1.5">{children}</dd>
    </div>
  );
}

function DevRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
      <dt className="w-32 shrink-0 text-status-neutral-solid">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function EvidenceBlock({
  evidence,
  reference,
}: {
  evidence: EvidenceItem[] | null;
  reference: string | null;
}) {
  const isUrl = reference ? /^https?:\/\//.test(reference) : false;
  return (
    <div className="space-y-3">
      {evidence && evidence.length > 0 ? (
        <ul className="space-y-2.5">
          {evidence.map((item, index) => (
            <li
              key={`${item.reference ?? item.summary}-${index}`}
              className="flex items-center justify-between gap-3 rounded-[9px] border border-border-subtle bg-background px-3.5 py-3"
            >
              <div className="flex min-w-0 items-center gap-[11px]">
                <span
                  className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full bg-status-fail-bg text-[11px] font-semibold text-status-fail-solid"
                  aria-hidden="true"
                >
                  ✗
                </span>
                <p className="text-[13px] leading-[1.45] text-foreground-secondary">
                  {item.summary}
                </p>
              </div>
              <TrustMark source={item.oracle_source} pill className="shrink-0" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          No failing assertions are recorded for this finding.
        </p>
      )}

      {reference ? (
        <div className="space-y-1">
          {isUrl ? (
            <a
              href={reference}
              target="_blank"
              rel="noreferrer"
              className="break-all font-mono text-[13px] text-accent hover:underline"
            >
              {reference}
            </a>
          ) : (
            <p className="break-all font-mono text-[13px] text-foreground">
              {reference}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            The stored evidence reference (the Playwright trace embed is coming).
          </p>
        </div>
      ) : null}

      {/* Screenshot evidence: a sibling backend slice adds has_screenshot + a
       *  GET /findings/{id}/screenshot endpoint. It isn't on trunk yet, so we show
       *  an honest placeholder rather than a broken image; wire it when present. */}
      <div className="rounded-[9px] border border-dashed border-border bg-surface px-3.5 py-4">
        <p className="text-[13px] font-medium text-foreground-secondary">Screenshot</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Screenshot capture isn&rsquo;t available for this finding yet.
        </p>
      </div>
    </div>
  );
}

function HistoryBlock({ finding }: { finding: Finding }) {
  const history = finding.history ?? null;
  const classification = history?.classification ?? finding.status;
  const viz = historyViz(classification);
  const isFlaky = classification === "flaky";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold",
            viz.bg,
            viz.text,
          )}
        >
          <span
            className={cn("h-1.5 w-1.5 rounded-full", viz.dot)}
            aria-hidden="true"
          />
          {viz.label}
        </span>
        <span className="text-sm text-muted-foreground">
          {statusMeaning(classification)}
        </span>
      </div>

      {history ? (
        <>
          {/* Reproduction rate for a flaky finding — we report the real recurrence
           *  count; there's no total-runs denominator on the payload, so we don't
           *  imply "of N". */}
          <p className="text-xs text-muted-foreground">
            {isFlaky ? "Failed in " : "Seen in "}
            {history.occurrence_count} {history.occurrence_count === 1 ? "run" : "runs"}{" "}
            of recent history.
          </p>
          {history.first_seen_run || history.last_seen_run ? (
            <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border-subtle bg-border-subtle sm:grid-cols-2">
              <ExpectedActualCell label="First seen">
                <span className="break-all font-mono text-xs text-foreground-secondary">
                  {history.first_seen_run ?? "—"}
                </span>
              </ExpectedActualCell>
              <ExpectedActualCell label="Last seen">
                <span className="break-all font-mono text-xs text-foreground-secondary">
                  {history.last_seen_run ?? "—"}
                </span>
              </ExpectedActualCell>
            </dl>
          ) : null}
        </>
      ) : (
        <p className="text-xs text-muted-foreground">
          No cross-run history is recorded for this finding yet.
        </p>
      )}
    </div>
  );
}

/** The expected HTTP status from the finding's `expected` contract, if it carries
 *  one — rendered as a string, or null when absent/typed differently. */
function readExpectedStatus(
  expected: Record<string, unknown> | null | undefined,
): string | null {
  if (!expected) return null;
  const status = expected.status;
  return typeof status === "number" || typeof status === "string"
    ? String(status)
    : null;
}
