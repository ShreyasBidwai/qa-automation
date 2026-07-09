import { AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { IncidentListItem } from "@/lib/api/types";
import { incidentApi } from "@/lib/api/client";
import { relativeTime } from "@/lib/time";
import { usePagedList } from "@/lib/usePagedList";

import { AdminDetailDrawer } from "./AdminDetailDrawer";
import { AdminScreen } from "./AdminScreen";
import { useAdminResource } from "./useAdminResource";

const PAGE_SIZE = 25;
const ALL = "all";
const COLS = "grid-cols-[2fr_1fr_1fr_0.9fr]";

/** Internal incidents (GET /incidents, ADR-0047) — captured failures with tracebacks. */
export function AdminIncidentsPage() {
  return (
    <AdminScreen
      icon={AlertTriangle}
      title="Incidents"
      subtitle="Captured internal failures, newest first"
      perm="view_ops"
    >
      <IncidentsBody />
    </AdminScreen>
  );
}

function IncidentsBody() {
  const [phase, setPhase] = useState<string>(ALL);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Accumulate the phases we've seen so the filter stays populated even after you narrow
  // to one phase (the backend matches phase exactly, so the union keeps every option).
  const [knownPhases, setKnownPhases] = useState<string[]>([]);

  const fetchPage = useCallback(
    (offset: number) =>
      incidentApi.list({
        phase: phase === ALL ? undefined : phase,
        limit: PAGE_SIZE,
        offset,
      }),
    [phase],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: phase });

  useEffect(() => {
    if (list.items.length === 0) return;
    setKnownPhases((prev) => {
      const next = new Set(prev);
      for (const item of list.items) next.add(item.phase);
      const merged = [...next].sort();
      return merged.length === prev.length ? prev : merged;
    });
  }, [list.items]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <select
          aria-label="Phase"
          value={phase}
          onChange={(event) => setPhase(event.target.value)}
          className="h-[34px] rounded-lg border border-border bg-surface px-3 text-[13px] font-medium text-status-neutral-fg transition-colors focus-visible:border-accent"
        >
          <option value={ALL}>All phases</option>
          {knownPhases.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>

      {list.loading ? (
        <SkeletonRows label="Loading incidents…" />
      ) : list.error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load incidents"
          description="This is usually temporary — the incidents service may be briefly unavailable."
          code={list.error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : list.items.length === 0 ? (
        <StatePanel
          icon={AlertTriangle}
          tone="success"
          title="No incidents"
          description={
            phase === ALL
              ? "Nothing has failed internally — Polaris is running clean."
              : "No incidents in this phase."
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
          <div
            className={`grid shrink-0 ${COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
          >
            <ColHead>Failure</ColHead>
            <ColHead>Phase</ColHead>
            <ColHead>Component</ColHead>
            <ColHead>When</ColHead>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {list.items.map((incident) => (
              <IncidentRow
                key={incident.id}
                incident={incident}
                onOpen={() => setSelectedId(incident.id)}
              />
            ))}
          </div>
          <div className="shrink-0 border-t border-border-subtle px-5 py-3">
            <Pagination
              offset={list.offset}
              pageSize={list.pageSize}
              total={list.total}
              hasPrev={list.hasPrev}
              hasNext={list.hasNext}
              onPrev={list.prev}
              onNext={list.next}
            />
          </div>
        </div>
      )}

      <IncidentDrawer incidentId={selectedId} onClose={() => setSelectedId(null)} />
    </>
  );
}

function IncidentRow({
  incident,
  onOpen,
}: {
  incident: IncidentListItem;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`grid ${COLS} w-full items-center border-b border-border-subtle px-5 py-3.5 text-left transition-colors last:border-b-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent`}
    >
      <span className="min-w-0 pr-3">
        <span className="block truncate font-mono text-[12.5px] font-medium text-status-fail-fg">
          {incident.exception_type}
        </span>
        <span className="block truncate text-[12px] text-status-neutral-solid">
          {incident.message}
        </span>
      </span>
      <span>
        <Badge level="flaky">{incident.phase}</Badge>
      </span>
      <span className="truncate text-[13px] text-status-neutral-fg">
        {incident.component ?? "—"}
      </span>
      <span className="text-xs text-status-neutral-solid">
        {relativeTime(incident.created_at)}
      </span>
    </button>
  );
}

// --- detail drawer -----------------------------------------------------------

function IncidentDrawer({
  incidentId,
  onClose,
}: {
  incidentId: string | null;
  onClose: () => void;
}) {
  const fetcher = useCallback(
    () => incidentApi.get(incidentId as string),
    [incidentId],
  );
  const detail = useAdminResource(fetcher, incidentId !== null);
  const incident = detail.data;

  return (
    <AdminDetailDrawer
      open={incidentId !== null}
      onClose={onClose}
      label={incident ? `Incident: ${incident.exception_type}` : "Incident"}
    >
      {detail.loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !incident ? (
        <p className="text-sm text-status-fail-fg">
          {detail.error ?? "Couldn't load this incident."}
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-mono text-base font-semibold text-status-fail-fg">
                {incident.exception_type}
              </h2>
              <Badge level="flaky">{incident.phase}</Badge>
            </div>
            <p className="mt-1.5 text-sm text-foreground">{incident.message}</p>
            <p className="mt-1 text-[12px] text-marker">
              {relativeTime(incident.created_at)}
            </p>
          </div>

          <dl className="grid grid-cols-1 gap-2 text-[12.5px]">
            <MetaRow label="Component" value={incident.component} />
            <MetaRow label="Project" value={incident.project_id} mono />
            <MetaRow label="Run" value={incident.run_id} mono />
            <MetaRow label="Fingerprint" value={incident.fingerprint} mono />
          </dl>

          <div>
            <h3 className="mb-2 text-sm font-semibold text-foreground">Traceback</h3>
            {incident.traceback ? (
              <pre className="max-h-[45vh] overflow-auto rounded-lg border border-border bg-background p-3.5 font-mono text-[11.5px] leading-relaxed text-status-neutral-fg">
                {incident.traceback}
              </pre>
            ) : (
              <p className="text-[13px] text-muted-foreground">
                No traceback was captured for this incident.
              </p>
            )}
          </div>
        </div>
      )}
    </AdminDetailDrawer>
  );
}

function MetaRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-status-neutral-solid">{label}</dt>
      <dd
        className={
          mono ? "truncate font-mono text-[11.5px] text-foreground" : "text-foreground"
        }
      >
        {value ?? "—"}
      </dd>
    </div>
  );
}

function ColHead({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
      {children}
    </span>
  );
}
