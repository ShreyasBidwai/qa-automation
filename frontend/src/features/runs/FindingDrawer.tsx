import { ChevronDown, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Drawer } from "@/components/Drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Finding } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { confidenceSpec, layerSpec, severitySpec, statusSpec } from "./findingBadges";
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
                <Flag>The expected oracle isn&rsquo;t exposed in the API yet.</Flag>
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

        <Section title="Cross-layer path">
          <CrossLayerRibbon finding={finding} />
        </Section>

        <Section title="Confidence">
          <p className="text-sm text-foreground">
            {confidenceRationale(finding.oracle_source)}
          </p>
        </Section>

        <Section title="Evidence">
          {finding.evidence_ref ? (
            <EvidenceRef reference={finding.evidence_ref} />
          ) : (
            <Flag>No evidence reference is exposed for this finding yet.</Flag>
          )}
        </Section>

        <Section title="History">
          <p className="text-sm text-foreground">{statusMeaning(finding.status)}</p>
          {finding.history && finding.history.length > 0 ? (
            <ol className="mt-3 space-y-1.5">
              {finding.history.map((entry, index) => (
                <li
                  key={`${entry.run_id}-${index}`}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="font-mono text-muted-foreground">
                    {entry.run_id}
                  </span>
                  <span className="text-foreground">{entry.status}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              No run-by-run timeline is exposed yet — showing the current status.
            </p>
          )}
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
  // A "not exposed yet" note — graceful, never invented data.
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
