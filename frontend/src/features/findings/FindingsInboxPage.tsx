import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Select } from "@/components/ui/select";
import { findingApi } from "@/lib/api/client";
import type { Finding } from "@/lib/api/types";
import { usePagedList } from "@/lib/usePagedList";

import { FindingDrawer } from "../runs/FindingDrawer";
import { FindingRow } from "../runs/FindingRow";
import {
  ALL,
  EMPTY_FILTERS,
  applyFilters,
  type FindingFilters,
} from "../runs/findingFilters";

const PAGE_SIZE = 25;

/**
 * The findings inbox — "what's broken right now" across every project (GET
 * /findings). The open findings only (the API excludes muted/resolved), ranked,
 * with the shared run-dashboard row treatment. Selecting one opens the same
 * detail drawer (triage included) keyed to that finding's run.
 */
export function FindingsInboxPage() {
  const fetchPage = useCallback(
    (offset: number) => findingApi.listOpen({ limit: PAGE_SIZE, offset }),
    [],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: "inbox" });

  const [filters, setFilters] = useState<FindingFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Reflect a triage change locally so the row updates without a refetch.
  const [overrides, setOverrides] = useState<Record<string, Finding>>({});

  const items = useMemo(
    () => list.items.map((finding) => overrides[finding.id] ?? finding),
    [list.items, overrides],
  );
  const visible = applyFilters(items, filters);
  const selected = items.find((finding) => finding.id === selectedId) ?? null;

  return (
    <>
      <PageHeader
        title="Findings"
        description="Open across every project, worst first."
      />
      <main className="flex-1 px-6 py-8">
        {list.loading ? (
          <SkeletonRows label="Loading findings…" />
        ) : list.error ? (
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load findings"
            description="Polaris couldn't reach the findings service. This is usually temporary."
            code={list.error}
            actions={
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent-hover"
              >
                Retry
              </button>
            }
          />
        ) : items.length === 0 ? (
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
        ) : (
          <div className="space-y-3">
            <Filters filters={filters} onChange={setFilters} count={visible.length} />
            {visible.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border bg-surface px-6 py-10 text-center text-sm text-muted-foreground">
                No findings match these filters.
              </p>
            ) : (
              <div className="overflow-hidden rounded-xl border border-border bg-surface">
                {visible.map((finding) => (
                  <FindingRow
                    key={finding.id}
                    finding={finding}
                    selected={finding.id === selectedId}
                    onSelect={(f) => setSelectedId(f.id)}
                  />
                ))}
              </div>
            )}
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
        )}
      </main>

      <FindingDrawer
        finding={selected}
        runId={selected?.run_id ?? ""}
        onClose={() => setSelectedId(null)}
        onTriaged={(updated) =>
          setOverrides((current) => ({ ...current, [updated.id]: updated }))
        }
      />
    </>
  );
}

function Filters({
  filters,
  onChange,
  count,
}: {
  filters: FindingFilters;
  onChange: (next: FindingFilters) => void;
  count: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <FilterSelect
        label="Severity"
        value={filters.severity}
        onChange={(v) => onChange({ ...filters, severity: v })}
        options={[
          ["critical", "Critical"],
          ["major", "Major"],
          ["minor", "Minor"],
        ]}
      />
      <FilterSelect
        label="Layer"
        value={filters.layer}
        onChange={(v) => onChange({ ...filters, layer: v })}
        options={[
          ["ui", "ui"],
          ["api", "api"],
          ["db", "db"],
        ]}
      />
      <FilterSelect
        label="Trust"
        value={filters.confidence}
        onChange={(v) => onChange({ ...filters, confidence: v })}
        options={[
          ["rule-derived", "Rule-derived"],
          ["characterization", "Characterization"],
          ["spec-grounded", "Spec-grounded"],
        ]}
      />
      <FilterSelect
        label="History"
        value={filters.status}
        onChange={(v) => onChange({ ...filters, status: v })}
        options={[
          ["new", "New"],
          ["regression", "Regression"],
          ["flaky", "Flaky"],
          ["known", "Known"],
        ]}
      />
      <span className="ml-auto font-mono text-xs text-muted-foreground">
        {count} shown
      </span>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  const id = `inbox-filter-${label.toLowerCase()}`;
  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <Select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 w-auto"
      >
        <option value={ALL}>All</option>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </Select>
    </div>
  );
}
