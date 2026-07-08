import { AlertTriangle, Building2, Search, X } from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { Skeleton, SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { AdminOrgListItem, PlanItem } from "@/lib/api/types";
import { adminApi, planApi } from "@/lib/api/client";
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
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">{org.name}</h2>
              {org.suspended ? (
                <Badge level="fail">Suspended</Badge>
              ) : (
                <Badge level="pass">Active</Badge>
              )}
              <Badge level="info">{planLabel(org.plan_key)} plan</Badge>
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

          <BillingSection
            orgId={org.id}
            planKey={org.plan_key}
            onPlanChanged={() => {
              detail.reload();
              onChanged();
            }}
          />

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

// --- billing (B4, ADR-0069) --------------------------------------------------

const USAGE_WINDOW_DAYS = 30;

/** Capitalize a plan key for display (`team` → "Team"). A stable read even before the
 *  plan catalog loads (the badge shows immediately from the org detail). */
function planLabel(key: string): string {
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : "Free";
}

/**
 * The org's plan + metered AI cost, inside the tenant drawer. The plan SELECTOR shows
 * only with MANAGE_BILLING (a 422 unknown-plan / 403 surfaces inline); the COST panel
 * shows only with VIEW_BILLING. The server stays authoritative on both — the UI only
 * hides an action it already knows will be refused.
 */
function BillingSection({
  orgId,
  planKey,
  onPlanChanged,
}: {
  orgId: string;
  planKey: string;
  onPlanChanged: () => void;
}) {
  const { hasPerm } = useStaff();
  const canManageBilling = hasPerm("manage_billing");
  const canViewBilling = hasPerm("view_billing");

  // Neither price nor bill → keep the drawer quiet (the plan badge already shows above).
  if (!canManageBilling && !canViewBilling) return null;

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-foreground">Plan &amp; billing</h3>
      <div className="flex flex-col gap-3">
        {canManageBilling ? (
          <PlanSelector orgId={orgId} planKey={planKey} onPlanChanged={onPlanChanged} />
        ) : null}
        {canViewBilling ? <UsagePanel orgId={orgId} /> : null}
      </div>
    </div>
  );
}

function PlanSelector({
  orgId,
  planKey,
  onPlanChanged,
}: {
  orgId: string;
  planKey: string;
  onPlanChanged: () => void;
}) {
  const plansFetcher = useCallback(() => planApi.list(), []);
  const plans = useAdminResource(plansFetcher);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function change(next: string) {
    if (next === planKey) return;
    setError(null);
    setSaved(false);
    setBusy(true);
    const result = await adminApi.setOrgPlan(orgId, next);
    setBusy(false);
    if (result.ok) {
      setSaved(true);
      onPlanChanged();
      return;
    }
    // A 422 (unknown plan) / 403 (insufficient) arrives already voiced from the client.
    setError(result.error ?? "Couldn't update the plan.");
  }

  const catalog: PlanItem[] = plans.data?.items ?? [];
  // Keep the current key selectable even if the catalog omits it (a legacy/private tier),
  // so the <select> value always matches an option and never renders blank.
  const hasCurrent = catalog.some((plan) => plan.key === planKey);

  return (
    <div className="rounded-lg border border-border-subtle bg-background px-3.5 py-3">
      <label
        htmlFor="org-plan"
        className="text-[11px] font-medium text-muted-foreground"
      >
        Assign plan
      </label>
      <Select
        id="org-plan"
        className="mt-1.5"
        value={planKey}
        disabled={busy || plans.loading}
        onChange={(event) => change(event.target.value)}
      >
        {!hasCurrent ? <option value={planKey}>{planLabel(planKey)}</option> : null}
        {catalog.map((plan) => (
          <option key={plan.key} value={plan.key}>
            {plan.name}
          </option>
        ))}
      </Select>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-status-fail-fg">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p role="status" className="mt-2 text-xs text-status-pass-fg">
          Plan updated.
        </p>
      ) : null}
    </div>
  );
}

function UsagePanel({ orgId }: { orgId: string }) {
  const fetcher = useCallback(
    () => adminApi.orgUsage(orgId, USAGE_WINDOW_DAYS),
    [orgId],
  );
  const { data, loading, error } = useAdminResource(fetcher);

  if (loading) return <Skeleton className="h-28 rounded-lg" />;
  if (error || !data) {
    return (
      <p className="rounded-lg border border-border-subtle bg-background px-3.5 py-3 text-[13px] text-muted-foreground">
        {error ?? "Couldn't load usage."}
      </p>
    );
  }

  const tokens = data.input_tokens + data.output_tokens;
  return (
    <div className="rounded-lg border border-border-subtle bg-background px-3.5 py-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-muted-foreground">
          AI cost · last {data.since_days}d
        </span>
        <span className="text-sm font-semibold tabular-nums text-foreground">
          {formatUsd(data.total_cost_usd)}
        </span>
      </div>
      <div className="mt-2.5 grid grid-cols-3 gap-2">
        <MiniStat label="Runs" value={data.run_count.toLocaleString()} />
        <MiniStat label="Calls" value={data.invocation_count.toLocaleString()} />
        <MiniStat label="Tokens" value={compactTokens(tokens)} />
      </div>
      {data.by_model.length > 0 ? (
        <div className="mt-3 border-t border-border-subtle pt-2.5">
          <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
            By model
          </div>
          <div className="flex flex-col gap-1">
            {data.by_model.map((model) => (
              <div
                key={model.model ?? "unknown"}
                className="flex items-center justify-between gap-3 text-[12.5px]"
              >
                <span className="min-w-0 truncate font-mono text-status-neutral-fg">
                  {model.model ?? "unknown"}
                </span>
                <span className="flex-none tabular-nums text-muted-foreground">
                  {model.invocation_count.toLocaleString()} ·{" "}
                  {formatUsd(model.total_cost_usd)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10.5px] text-status-neutral-solid">{label}</div>
      <div className="text-[13px] font-semibold tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}

/** USD with cents — the metered AI cost per org is small, so cents are meaningful. */
function formatUsd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/** Compact large token totals (12.3K / 4.5M) so the row stays legible. */
function compactTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
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
