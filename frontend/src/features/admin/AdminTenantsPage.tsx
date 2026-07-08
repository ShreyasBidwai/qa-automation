import { AlertTriangle, Building2, Search, X } from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AdminOrgListItem } from "@/lib/api/types";
import { adminApi } from "@/lib/api/client";
import { useStaff } from "@/lib/auth/useStaff";
import { relativeTime } from "@/lib/time";
import { usePagedList } from "@/lib/usePagedList";

import { AdminDetailDrawer } from "./AdminDetailDrawer";
import { AdminScreen } from "./AdminScreen";
import { useAdminResource, useDebouncedValue } from "./useAdminResource";

const PAGE_SIZE = 25;
const COLS = "grid-cols-[2.2fr_0.8fr_0.8fr_1fr_0.9fr]";

/** Tenants (GET /admin/orgs) — searchable, paginated org list with a detail drawer. */
export function AdminTenantsPage() {
  return (
    <AdminScreen
      icon={Building2}
      title="Tenants"
      subtitle="Every organization on the instance"
      perm="view_tenants"
    >
      <TenantsBody />
    </AdminScreen>
  );
}

function TenantsBody() {
  const { hasPerm } = useStaff();
  const canManage = hasPerm("manage_tenants");

  const [query, setQuery] = useState("");
  const search = useDebouncedValue(query.trim());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Bumping this changes `fetchPage`'s identity, which re-runs the current page — the
  // way we refresh the list after a suspend/reactivate without leaving the page.
  const [refreshNonce, setRefreshNonce] = useState(0);

  const fetchPage = useCallback(
    (offset: number) => adminApi.listOrgs({ search, limit: PAGE_SIZE, offset }),
    [search, refreshNonce],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: search });

  return (
    <>
      <SearchRow
        value={query}
        onChange={setQuery}
        placeholder="Search organizations…"
      />

      {list.loading ? (
        <SkeletonRows label="Loading tenants…" />
      ) : list.error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load tenants"
          description="This is usually temporary — the admin service may be briefly unavailable."
          code={list.error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : list.items.length === 0 ? (
        <StatePanel
          icon={Building2}
          title={search ? "No matching organizations" : "No organizations"}
          description={
            search
              ? "No organizations match that search."
              : "There are no organizations on this instance yet."
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
          <div
            className={`grid shrink-0 ${COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
          >
            <ColHead>Organization</ColHead>
            <ColHead>Members</ColHead>
            <ColHead>Projects</ColHead>
            <ColHead>Created</ColHead>
            <ColHead>Status</ColHead>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {list.items.map((org) => (
              <OrgRow key={org.id} org={org} onOpen={() => setSelectedId(org.id)} />
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

      <OrgDrawer
        orgId={selectedId}
        canManage={canManage}
        onClose={() => setSelectedId(null)}
        onChanged={() => setRefreshNonce((current) => current + 1)}
      />
    </>
  );
}

function OrgRow({ org, onOpen }: { org: AdminOrgListItem; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`grid ${COLS} w-full items-center border-b border-border-subtle px-5 py-3.5 text-left transition-colors last:border-b-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent`}
    >
      <span className="min-w-0 pr-3">
        <span className="block truncate text-sm font-medium text-foreground">
          {org.name}
        </span>
        {org.is_personal ? (
          <span className="text-[11px] text-status-neutral-solid">Personal</span>
        ) : null}
      </span>
      <span className="text-[13px] tabular-nums text-status-neutral-fg">
        {org.member_count}
      </span>
      <span className="text-[13px] tabular-nums text-status-neutral-fg">
        {org.project_count}
      </span>
      <span className="text-xs text-status-neutral-solid">
        {relativeTime(org.created_at)}
      </span>
      <span>
        {org.suspended ? (
          <Badge level="fail">Suspended</Badge>
        ) : (
          <Badge level="pass">Active</Badge>
        )}
      </span>
    </button>
  );
}

// --- detail drawer -----------------------------------------------------------

function OrgDrawer({
  orgId,
  canManage,
  onClose,
  onChanged,
}: {
  orgId: string | null;
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const fetcher = useCallback(() => adminApi.getOrg(orgId as string), [orgId]);
  const detail = useAdminResource(fetcher, orgId !== null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleSuspend(suspend: boolean) {
    if (!orgId) return;
    setError(null);
    setBusy(true);
    const result = suspend
      ? await adminApi.suspendOrg(orgId)
      : await adminApi.reactivateOrg(orgId);
    setBusy(false);
    if (result.ok) {
      detail.reload();
      onChanged();
      return;
    }
    setError(result.error ?? "Couldn't update this organization.");
  }

  const org = detail.data;
  const members = useMemo(() => org?.members ?? [], [org]);

  return (
    <AdminDetailDrawer
      open={orgId !== null}
      onClose={onClose}
      label={org ? `Organization: ${org.name}` : "Organization"}
    >
      {detail.loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !org ? (
        <p className="text-sm text-status-fail-fg">
          {detail.error ?? "Couldn't load this organization."}
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">{org.name}</h2>
              {org.suspended ? (
                <Badge level="fail">Suspended</Badge>
              ) : (
                <Badge level="pass">Active</Badge>
              )}
            </div>
            <p className="mt-1 text-[12.5px] text-status-neutral-solid">
              {org.is_personal ? "Personal workspace" : "Team organization"} · created{" "}
              {relativeTime(org.created_at)}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <StatBox label="Members" value={org.member_count} />
            <StatBox label="Projects" value={org.project_count} />
          </div>

          {canManage ? (
            <div>
              {org.suspended ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => toggleSuspend(false)}
                >
                  {busy ? "Working…" : "Reactivate organization"}
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => toggleSuspend(true)}
                  className="border-status-fail-border text-status-fail-fg hover:bg-status-fail-bg"
                >
                  {busy ? "Working…" : "Suspend organization"}
                </Button>
              )}
              {error ? (
                <p role="alert" className="mt-2 text-xs text-status-fail-fg">
                  {error}
                </p>
              ) : null}
            </div>
          ) : null}

          <div>
            <h3 className="mb-2 text-sm font-semibold text-foreground">Members</h3>
            {members.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">No members.</p>
            ) : (
              <div className="overflow-hidden rounded-lg border border-border">
                {members.map((member) => (
                  <div
                    key={member.user_id}
                    className="flex items-center gap-3 border-b border-border-subtle px-3.5 py-2.5 last:border-b-0"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium text-foreground">
                        {member.name?.trim() || member.email}
                      </div>
                      <div className="truncate font-mono text-[11.5px] text-status-neutral-solid">
                        {member.email}
                      </div>
                    </div>
                    <Badge level="neutral">{member.role}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </AdminDetailDrawer>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-background px-3.5 py-3">
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}

// --- shared bits -------------------------------------------------------------

export function SearchRow({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="mb-4 flex shrink-0 items-center gap-2">
      <div className="relative w-full max-w-sm">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-status-neutral-solid"
          aria-hidden="true"
        />
        <Input
          type="search"
          aria-label={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="pl-9"
        />
        {value ? (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => onChange("")}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-status-neutral-solid hover:text-foreground"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        ) : null}
      </div>
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
