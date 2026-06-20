import { ChevronDown, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Drawer } from "@/components/Drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Finding } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import type { EvidenceItem, FindingHistory, FindingLocation } from "@/lib/api/types";

import {
  confidenceSpec,
  layerSpec,
  oracleTrustSpec,
  severitySpec,
  statusSpec,
} from "./findingBadges";
import { CrossLayerRibbon } from "./CrossLayerRibbon";
import { confidenceRationale, failureLine, statusMeaning } from "./findingDetail";

/** The finding detail "fix view" — opens from a findings-list row (T6.3). */
export function FindingDrawer({
  finding,
  onClose,
}: {
  finding: Finding | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      open={finding !== null}
      onClose={onClose}
      label={finding ? `Finding: ${finding.title}` : "Finding"}
    >
      {finding ? <FindingDetail finding={finding} onClose={onClose} /> : null}
    </Drawer>
  );
}

function FindingDetail({
  finding,
  onClose,
}: {
  finding: Finding;
  onClose: () => void;
}) {
  const severity = severitySpec(finding.severity);
  const layer = layerSpec(finding.layer);
  const confidence = confidenceSpec(finding.oracle_source);
  const status = statusSpec(finding.status);
  const observed = failureLine(finding);

  return (
    <>
      <header className="sticky top-0 z-10 border-b border-border bg-surface px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-medium text-foreground">{finding.title}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge level={severity.level}>{severity.label}</Badge>
              <Badge level={confidence.level}>{confidence.label}</Badge>
              <Badge level={layer.level}>{layer.label}</Badge>
              <Badge level={status.level}>{status.label}</Badge>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
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
        </div>
      </header>

      <div className="flex-1">
        <Section title="Expected vs observed">
          <div className="space-y-3">
            <Field label="Expected">
              {finding.expected ? (
                <pre className="overflow-x-auto rounded-md border border-border bg-background p-3 font-mono text-xs text-foreground">
                  {JSON.stringify(finding.expected, null, 2)}
                </pre>
              ) : (
                <Flag>No expected oracle is recorded for this finding.</Flag>
              )}
            </Field>
            <Field label="Observed">
              {observed ? (
                <p className="font-mono text-[13px] text-foreground">{observed}</p>
              ) : (
                <Flag>No observed-failure detail is available.</Flag>
              )}
              <p className="mt-1 text-xs text-muted-foreground">
                The full actual response/state is captured in the evidence trace, not as
                a field.
              </p>
            </Field>
          </div>
        </Section>

        <Section title="Location">
          <LocationBlock location={finding.location ?? null} />
          <div className="mt-3">
            <CrossLayerRibbon finding={finding} />
          </div>
        </Section>

        <Section title="Confidence">
          <p className="text-sm text-foreground">
            {confidenceRationale(finding.oracle_source)}
          </p>
          {finding.confidence_mixed ? (
            <p className="mt-2 text-xs text-muted-foreground">
              The grouped tests disagree on oracle tier — the strongest sets the
              badge above.
            </p>
          ) : null}
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
      </div>

      <FindingActions />
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="border-b border-border">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-5 py-3 text-left text-sm font-medium text-foreground hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
      >
        {title}
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>
      {open ? <div className="px-5 pb-5">{children}</div> : null}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

function Flag({ children }: { children: ReactNode }) {
  // A graceful fallback note for a genuinely-absent field — never invented data.
  return (
    <p className="rounded-md border border-dashed border-border bg-background px-3 py-2 text-xs text-muted-foreground">
      {children}
    </p>
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

function LocationBlock({ location }: { location: FindingLocation | null }) {
  const anchor = location?.anchor ?? null;
  if (!anchor || !anchor.node_type) {
    return (
      <p className="text-sm text-muted-foreground">
        The failing node couldn&rsquo;t be resolved for this finding.
      </p>
    );
  }
  return (
    <p className="text-sm">
      <span className="text-muted-foreground">Failing node: </span>
      <span className="font-mono text-foreground">{anchor.label}</span>{" "}
      <span className="text-xs text-muted-foreground">({anchor.node_type})</span>
    </p>
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
        <ul className="space-y-2">
          {evidence.map((item, index) => {
            const trust = oracleTrustSpec(item.oracle_source);
            return (
              <li
                key={`${item.reference ?? item.summary}-${index}`}
                className="rounded-md border border-border bg-background p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[13px] text-foreground">{item.summary}</p>
                  <Badge level={trust.level} className="shrink-0">
                    {trust.label}
                  </Badge>
                </div>
                {item.reference ? (
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {item.reference}
                  </p>
                ) : null}
              </li>
            );
          })}
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
  return (
    <div className="space-y-2">
      <p className="text-sm text-foreground">{statusMeaning(classification)}</p>
      {history ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Occurrences</dt>
          <dd className="text-foreground">
            seen in {history.occurrence_count}{" "}
            {history.occurrence_count === 1 ? "run" : "runs"} (recent history)
          </dd>
          {history.first_seen_run ? (
            <>
              <dt className="text-muted-foreground">First seen</dt>
              <dd className="break-all font-mono text-foreground">
                {history.first_seen_run}
              </dd>
            </>
          ) : null}
          {history.last_seen_run ? (
            <>
              <dt className="text-muted-foreground">Last seen</dt>
              <dd className="break-all font-mono text-foreground">
                {history.last_seen_run}
              </dd>
            </>
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}

function FindingActions() {
  // Workflow actions, grouped apart from details (Sentry's lesson). Placeholder
  // and clearly disabled until the backend wires them.
  return (
    <div className="border-t border-border bg-background px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" disabled>
          Export to tracker
        </Button>
        <Button variant="outline" size="sm" disabled>
          Change status
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Triage actions are coming in a later sprint.
      </p>
    </div>
  );
}
