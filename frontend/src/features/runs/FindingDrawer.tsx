import { X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Drawer } from "@/components/Drawer";
import { Button } from "@/components/ui/button";
import { TrustMark } from "@/components/ui/TrustMark";
import { runApi } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import type {
  EvidenceItem,
  Finding,
  FindingHistory,
  TriageStatusValue,
} from "@/lib/api/types";

import { triageSpec } from "./findingBadges";
import { statusMeaning } from "./findingDetail";
import { historyViz, severityViz } from "./findingViz";
import { BlastPathRibbon } from "./BlastPathRibbon";

/** The finding detail "fix view" — screen 8 in a right-side drawer (T6.3). */
export function FindingDrawer({
  finding,
  runId,
  onClose,
  onTriaged,
}: {
  finding: Finding | null;
  runId: string;
  onClose: () => void;
  onTriaged?: (updated: Finding) => void;
}) {
  return (
    <Drawer
      open={finding !== null}
      onClose={onClose}
      label={finding ? `Finding: ${finding.title}` : "Finding"}
    >
      {finding ? (
        <FindingDetail
          finding={finding}
          runId={runId}
          onClose={onClose}
          onTriaged={onTriaged}
        />
      ) : null}
    </Drawer>
  );
}

function FindingDetail({
  finding,
  runId,
  onClose,
  onTriaged,
}: {
  finding: Finding;
  runId: string;
  onClose: () => void;
  onTriaged?: (updated: Finding) => void;
}) {
  const severity = severityViz(finding.severity);

  return (
    <>
      <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-surface px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h2 className="text-[17px] font-semibold leading-tight text-foreground">
              {finding.title}
            </h2>
            <span
              className={cn(
                "shrink-0 rounded px-2 py-0.5 text-[11px] font-semibold tracking-[0.02em]",
                severity.pill,
              )}
            >
              {severity.label}
            </span>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            explains {finding.explains_count}{" "}
            {finding.explains_count === 1 ? "test" : "tests"}
          </p>
        </div>
        <button
          type="button"
          data-autofocus
          onClick={onClose}
          aria-label="Close"
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <TriagePanel
        key={finding.id}
        finding={finding}
        runId={runId}
        onTriaged={onTriaged}
      />

      <FieldGrid finding={finding} />

      <Section title="Blast path">
        <BlastPathRibbon finding={finding} />
      </Section>

      <Section title="Evidence">
        <EvidenceList
          evidence={finding.evidence ?? null}
          reference={finding.evidence_ref ?? null}
        />
      </Section>

      <Section title="History">
        <HistoryBlock history={finding.history ?? null} status={finding.status} />
      </Section>
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-border px-5 py-5">
      <h3 className="mb-3.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

function FieldGrid({ finding }: { finding: Finding }) {
  const severity = severityViz(finding.severity);
  const triageStatus = finding.triage?.status ?? "open";
  const triage = triageSpec(triageStatus);
  const history = finding.history ?? null;
  return (
    <dl className="grid grid-cols-3 gap-px border-b border-border bg-border">
      <FieldCell label="Severity">
        <span className={cn("font-semibold", severity.fg)}>{severity.label}</span>
      </FieldCell>
      <FieldCell label="Confidence">
        <TrustMark source={finding.oracle_source} label />
      </FieldCell>
      <FieldCell label="Layer">
        <span className="font-mono text-xs text-foreground">{finding.layer}</span>
      </FieldCell>
      <FieldCell label="Status">
        <span className="text-foreground">{triage.label}</span>
      </FieldCell>
      <FieldCell label="First seen">
        <span className="break-all font-mono text-xs text-foreground">
          {history?.first_seen_run ?? "—"}
        </span>
      </FieldCell>
      <FieldCell label="Last seen">
        <span className="break-all font-mono text-xs text-foreground">
          {history?.last_seen_run ?? "—"}
        </span>
      </FieldCell>
    </dl>
  );
}

function FieldCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="bg-surface px-5 py-3.5">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1.5 text-[13px]">{children}</dd>
    </div>
  );
}

function EvidenceRef({ reference }: { reference: string }) {
  const isUrl = /^https?:\/\//.test(reference);
  return (
    <div className="space-y-1">
      {isUrl ? (
        <a
          href={reference}
          target="_blank"
          rel="noreferrer"
          className="break-all font-mono text-[13px] text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {reference}
        </a>
      ) : (
        <p className="break-all font-mono text-[13px] text-foreground">{reference}</p>
      )}
      <p className="text-xs text-muted-foreground">
        Embedding the Playwright trace is coming; this is the stored reference.
      </p>
    </div>
  );
}

function EvidenceList({
  evidence,
  reference,
}: {
  evidence: EvidenceItem[] | null;
  reference: string | null;
}) {
  return (
    <div className="space-y-3">
      {evidence && evidence.length > 0 ? (
        <ul className="space-y-2.5">
          {evidence.map((item, index) => (
            <li
              key={`${item.reference ?? item.summary}-${index}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-3.5 py-3"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span
                  className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full bg-status-fail-bg text-[11px] font-semibold text-status-fail-fg"
                  aria-hidden="true"
                >
                  ✗
                </span>
                <p className="text-[13px] text-foreground">{item.summary}</p>
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
      {reference ? <EvidenceRef reference={reference} /> : null}
    </div>
  );
}

function HistoryBlock({
  history,
  status,
}: {
  history: FindingHistory | null;
  status: string;
}) {
  const classification = history?.classification ?? status;
  const viz = historyViz(classification);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold",
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
        <p className="text-xs text-muted-foreground">
          Seen in {history.occurrence_count}{" "}
          {history.occurrence_count === 1 ? "run" : "runs"} (recent history).
        </p>
      ) : null}
    </div>
  );
}

// The triage dispositions a user can set (ADR-0027). "open" is the reopen action.
const TRIAGE_ACTIONS: { value: TriageStatusValue; label: string }[] = [
  { value: "acknowledged", label: "Acknowledge" },
  { value: "resolved", label: "Resolved" },
  { value: "wont_fix", label: "Won't fix" },
  { value: "false_positive", label: "False positive" },
  { value: "open", label: "Reopen" },
];

function TriagePanel({
  finding,
  runId,
  onTriaged,
}: {
  finding: Finding;
  runId: string;
  onTriaged?: (updated: Finding) => void;
}) {
  // Reflect the disposition from the PATCH response (server is the source of
  // truth); seeded from the finding's current triage.
  const [status, setStatus] = useState<string>(finding.triage?.status ?? "open");
  const [note, setNote] = useState(finding.triage?.note ?? "");
  const [triagedAt, setTriagedAt] = useState<string | null>(
    finding.triage?.triaged_at ?? null,
  );
  const [saving, setSaving] = useState<string | null>(null); // the status being saved
  const [error, setError] = useState<string | null>(null);

  async function set(next: TriageStatusValue) {
    setSaving(next);
    setError(null);
    const result = await runApi.triage(runId, finding.id, {
      status: next,
      note: note.trim() ? note.trim() : null,
    });
    setSaving(null);
    if (!result.ok || !result.data) {
      setError(result.error ?? "Could not save triage. Try again.");
      return;
    }
    setStatus(result.data.triage?.status ?? next);
    setTriagedAt(result.data.triage?.triaged_at ?? null);
    onTriaged?.(result.data);
  }

  return (
    <div className="border-b border-border bg-surface px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        {TRIAGE_ACTIONS.map((action) => {
          const active = status === action.value;
          return (
            <Button
              key={action.value}
              variant={active ? "primary" : "outline"}
              size="sm"
              aria-pressed={active}
              disabled={saving !== null}
              onClick={() => set(action.value)}
            >
              {action.label}
            </Button>
          );
        })}
      </div>

      <div className="mt-3">
        <label
          htmlFor="triage-note"
          className="text-xs font-medium text-muted-foreground"
        >
          Note (optional)
        </label>
        <textarea
          id="triage-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Why this disposition?"
          className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
      </div>

      {error ? (
        <p role="alert" className="mt-2 text-xs text-status-fail-fg">
          {error}
        </p>
      ) : null}
      {triagedAt ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Triaged {new Date(triagedAt).toLocaleString()}. Who triaged is recorded once
          sign-in lands.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          Not triaged yet — disposition follows the issue across runs.
        </p>
      )}
    </div>
  );
}
