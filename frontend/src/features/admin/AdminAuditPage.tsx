import { AlertTriangle, ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { StaffAuditItem } from "@/lib/api/types";
import { adminApi } from "@/lib/api/client";
import { relativeTime } from "@/lib/time";
import { usePagedList } from "@/lib/usePagedList";

import { AdminScreen } from "./AdminScreen";

const PAGE_SIZE = 25;
const ALL = "all";
const COLS = "grid-cols-[auto_1fr_1.2fr_1.4fr_0.9fr]";

/** Staff audit trail (GET /admin/audit) — filterable by action, newest first. */
export function AdminAuditPage() {
  return (
    <AdminScreen
      icon={ScrollText}
      title="Audit trail"
      subtitle="Every staff action, immutable and newest first"
      perm="view_audit"
    >
      <AuditBody />
    </AdminScreen>
  );
}

function AuditBody() {
  const [action, setAction] = useState<string>(ALL);
  const [knownActions, setKnownActions] = useState<string[]>([]);

  const fetchPage = useCallback(
    (offset: number) =>
      adminApi.listAudit({
        action: action === ALL ? undefined : action,
        limit: PAGE_SIZE,
        offset,
      }),
    [action],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: action });

  useEffect(() => {
    if (list.items.length === 0) return;
    setKnownActions((prev) => {
      const next = new Set(prev);
      for (const item of list.items) next.add(item.action);
      const merged = [...next].sort();
      return merged.length === prev.length ? prev : merged;
    });
  }, [list.items]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <select
          aria-label="Action"
          value={action}
          onChange={(event) => setAction(event.target.value)}
          className="h-[34px] rounded-lg border border-border bg-surface px-3 text-[13px] font-medium text-status-neutral-fg transition-colors focus-visible:border-accent"
        >
          <option value={ALL}>All actions</option>
          {knownActions.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>

      {list.loading ? (
        <SkeletonRows label="Loading audit trail…" />
      ) : list.error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load the audit trail"
          description="This is usually temporary — the admin service may be briefly unavailable."
          code={list.error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : list.items.length === 0 ? (
        <StatePanel
          icon={ScrollText}
          title="No audit entries"
          description={
            action === ALL
              ? "No staff actions have been recorded yet."
              : "No entries for this action."
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
          <div
            className={`grid shrink-0 ${COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
          >
            <span aria-hidden="true" />
            <ColHead>Actor</ColHead>
            <ColHead>Action</ColHead>
            <ColHead>Target</ColHead>
            <ColHead>When</ColHead>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {list.items.map((entry) => (
              <AuditRow key={entry.id} entry={entry} />
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
    </>
  );
}

function AuditRow({ entry }: { entry: StaffAuditItem }) {
  const [open, setOpen] = useState(false);
  const hasDetail = entry.detail && Object.keys(entry.detail).length > 0;
  const target =
    entry.target_type && entry.target_id
      ? `${entry.target_type} · ${entry.target_id}`
      : (entry.target_type ?? entry.target_id ?? "—");

  return (
    <div className="border-b border-border-subtle last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={!hasDetail}
        className={`grid ${COLS} w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent disabled:cursor-default disabled:hover:bg-transparent`}
      >
        <span className="text-status-neutral-solid">
          {hasDetail ? (
            open ? (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            )
          ) : (
            <span className="inline-block h-3.5 w-3.5" aria-hidden="true" />
          )}
        </span>
        <span className="min-w-0 truncate font-mono text-[12px] text-foreground">
          {entry.actor_email}
        </span>
        <span className="min-w-0">
          <Badge level="info">{entry.action}</Badge>
        </span>
        <span className="min-w-0 truncate font-mono text-[11.5px] text-status-neutral-fg">
          {target}
        </span>
        <span className="text-xs text-status-neutral-solid">
          {relativeTime(entry.created_at)}
        </span>
      </button>
      {open && hasDetail ? (
        <pre className="mx-5 mb-3 max-h-64 overflow-auto rounded-lg border border-border bg-background p-3 font-mono text-[11.5px] leading-relaxed text-status-neutral-fg">
          {JSON.stringify(entry.detail, null, 2)}
        </pre>
      ) : null}
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
