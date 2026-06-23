import { AlertTriangle, CheckCircle2, Inbox, MousePointerClick } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Link } from "@/components/Link";
import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { findingApi } from "@/lib/api/client";
import type { Finding } from "@/lib/api/types";
import { usePagedList } from "@/lib/usePagedList";

import { FindingDetail } from "../runs/FindingDetail";
import { FindingFilterBar } from "../runs/FindingFilterBar";
import { FindingRow } from "../runs/FindingRow";
import {
  EMPTY_FILTERS,
  applyFilters,
  type FindingFilters,
} from "../runs/findingFilters";

const PAGE_SIZE = 25;

/**
 * The findings inbox — "what's broken right now" across every project, reproducing
 * Polaris Findings Inbox.dc.html as a master-detail: a ranked list on the left,
 * the shared FindingDetail panel on the right. Bound to the cross-run open-findings
 * aggregation (GET /findings, ADR-0028) — the open findings only, severity-ranked,
 * never re-derived client-side. Selecting one opens the same detail (triage wired)
 * keyed to that finding's run. The dashboard's filter pills filter the list.
 */
export function FindingsInboxPage() {
  const fetchPage = useCallback(
    (offset: number) => findingApi.listOpen({ limit: PAGE_SIZE, offset }),
    [],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: "inbox" });

  const [filters, setFilters] = useState<FindingFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Reflect a triage change locally so the row + panel update without a refetch.
  const [overrides, setOverrides] = useState<Record<string, Finding>>({});

  const items = useMemo(
    () => list.items.map((finding) => overrides[finding.id] ?? finding),
    [list.items, overrides],
  );
  const visible = applyFilters(items, filters);
  // Default to the first finding (the file shows one selected on load); a click
  // pins another. Fall back across filtering so the panel is never blank.
  const selected =
    items.find((finding) => finding.id === selectedId) ??
    visible[0] ??
    items[0] ??
    null;

  return (
    <div className="flex flex-col min-[1024px]:h-full">
      <InboxHeader total={list.total} loading={list.loading} />

      {list.loading ? (
        <div className="flex-1 px-6 py-8">
          <SkeletonRows label="Loading findings…" />
        </div>
      ) : list.error ? (
        <div className="flex items-center justify-center px-6 py-8 min-[1024px]:min-h-0 min-[1024px]:flex-1">
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load findings"
            description="Polaris couldn't reach the findings service. This is usually temporary."
            code={list.error}
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
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center px-6 py-8 min-[1024px]:min-h-0 min-[1024px]:flex-1">
          <StatePanel
            icon={CheckCircle2}
            tone="success"
            title="Nothing's broken right now"
            description="No open findings across your projects — the latest runs came back clean. Polaris keeps watching as the code changes."
            actions={
              <Link
                to="/runs"
                className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground hover:bg-background"
              >
                View runs
              </Link>
            }
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col min-[1024px]:flex-row">
          <section
            aria-label="Findings"
            className="flex flex-col border-b border-border bg-surface min-[1024px]:min-h-0 min-[1024px]:w-[46%] min-[1024px]:min-w-[420px] min-[1024px]:border-b-0 min-[1024px]:border-r"
          >
            <div className="flex-none border-b border-border-subtle px-[18px] py-3">
              <div className="flex items-center justify-between gap-3">
                <FindingFilterBar filters={filters} onChange={setFilters} />
                <span className="shrink-0 font-mono text-[11px] text-status-neutral-solid">
                  {visible.length} shown
                </span>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {visible.length === 0 ? (
                <div className="px-6 py-10 text-center">
                  <p className="text-sm text-muted-foreground">
                    No findings match these filters.
                  </p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-3"
                    onClick={() => setFilters(EMPTY_FILTERS)}
                  >
                    Clear filters
                  </Button>
                </div>
              ) : (
                visible.map((finding) => (
                  <FindingRow
                    key={finding.id}
                    finding={finding}
                    selected={finding.id === selected?.id}
                    onSelect={(f) => setSelectedId(f.id)}
                  />
                ))
              )}
            </div>

            {list.total > list.pageSize ? (
              <div className="flex-none border-t border-border-subtle px-[18px] py-2.5">
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
            ) : null}
          </section>

          <section
            aria-label="Finding detail"
            className="flex flex-col overflow-hidden bg-surface min-[1024px]:min-h-0 min-[1024px]:flex-1"
          >
            <div className="min-h-0 flex-1 overflow-y-auto">
              {selected ? (
                <FindingDetail
                  finding={selected}
                  runId={selected.run_id ?? ""}
                  onTriaged={(updated) =>
                    setOverrides((current) => ({ ...current, [updated.id]: updated }))
                  }
                />
              ) : (
                <SelectAFinding />
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function InboxHeader({ total, loading }: { total: number; loading: boolean }) {
  return (
    <div className="flex flex-none items-center gap-3 border-b border-border bg-surface px-6 py-[18px]">
      <span className="flex h-7 w-7 flex-none items-center justify-center rounded-[7px] border-[1.5px] border-marker">
        <Inbox className="h-3.5 w-3.5 text-status-neutral-solid" aria-hidden="true" />
      </span>
      <h1 className="text-[18px] font-semibold tracking-[-0.01em] text-foreground">
        Findings
      </h1>
      {!loading ? (
        <span className="rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] font-semibold tabular-nums text-accent">
          {total}
        </span>
      ) : null}
      <span className="text-[13px] text-status-neutral-solid">
        Open across every project, worst first
      </span>
    </div>
  );
}

function SelectAFinding() {
  return (
    <div className="flex h-full items-center justify-center">
      <StatePanel
        size="sm"
        icon={MousePointerClick}
        title="Select a finding"
        description="Pick a finding on the left to see its blast path, evidence, and history."
      />
    </div>
  );
}
