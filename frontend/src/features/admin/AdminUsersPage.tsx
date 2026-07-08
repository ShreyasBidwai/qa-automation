import { AlertTriangle, Users } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AdminUserListItem, StaffRole } from "@/lib/api/types";
import { adminApi } from "@/lib/api/client";
import { useStaff } from "@/lib/auth/useStaff";
import { relativeTime } from "@/lib/time";
import { usePagedList } from "@/lib/usePagedList";

import { AdminDetailDrawer } from "./AdminDetailDrawer";
import { AdminScreen } from "./AdminScreen";
import { SearchRow } from "./AdminTenantsPage";
import { useAdminResource, useDebouncedValue } from "./useAdminResource";

const PAGE_SIZE = 25;
const COLS = "grid-cols-[2.2fr_0.7fr_1fr_1fr_0.9fr]";
const STAFF_ROLES: StaffRole[] = ["superadmin", "support", "billing", "read_only_ops"];

function humanizeRole(role: string): string {
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/** Users (GET /admin/users) — searchable, paginated user list with a detail drawer. */
export function AdminUsersPage() {
  return (
    <AdminScreen
      icon={Users}
      title="Users"
      subtitle="Every account on the instance"
      perm="view_users"
    >
      <UsersBody />
    </AdminScreen>
  );
}

function UsersBody() {
  const { hasPerm } = useStaff();
  const canManage = hasPerm("manage_users");

  const [query, setQuery] = useState("");
  const search = useDebouncedValue(query.trim());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const fetchPage = useCallback(
    (offset: number) => adminApi.listUsers({ search, limit: PAGE_SIZE, offset }),
    [search, refreshNonce],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: search });

  return (
    <>
      <SearchRow value={query} onChange={setQuery} placeholder="Search users…" />

      {list.loading ? (
        <SkeletonRows label="Loading users…" />
      ) : list.error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load users"
          description="This is usually temporary — the admin service may be briefly unavailable."
          code={list.error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : list.items.length === 0 ? (
        <StatePanel
          icon={Users}
          title={search ? "No matching users" : "No users"}
          description={
            search ? "No users match that search." : "There are no users to show."
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
          <div
            className={`grid shrink-0 ${COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
          >
            <ColHead>User</ColHead>
            <ColHead>Orgs</ColHead>
            <ColHead>Staff role</ColHead>
            <ColHead>Created</ColHead>
            <ColHead>Status</ColHead>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {list.items.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                onOpen={() => setSelectedId(user.id)}
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

      <UserDrawer
        userId={selectedId}
        canManage={canManage}
        onClose={() => setSelectedId(null)}
        onChanged={() => setRefreshNonce((current) => current + 1)}
      />
    </>
  );
}

function UserRow({ user, onOpen }: { user: AdminUserListItem; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`grid ${COLS} w-full items-center border-b border-border-subtle px-5 py-3.5 text-left transition-colors last:border-b-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent`}
    >
      <span className="min-w-0 pr-3">
        <span className="block truncate text-sm font-medium text-foreground">
          {user.name?.trim() || user.email}
        </span>
        <span className="block truncate font-mono text-[11.5px] text-status-neutral-solid">
          {user.email}
        </span>
      </span>
      <span className="text-[13px] tabular-nums text-status-neutral-fg">
        {user.org_count}
      </span>
      <span>
        {user.staff_role ? (
          <Badge level="info">{humanizeRole(user.staff_role)}</Badge>
        ) : (
          <span className="text-sm text-marker">—</span>
        )}
      </span>
      <span className="text-xs text-status-neutral-solid">
        {relativeTime(user.created_at)}
      </span>
      <span>
        {user.is_active ? (
          <Badge level="pass">Active</Badge>
        ) : (
          <Badge level="neutral">Inactive</Badge>
        )}
      </span>
    </button>
  );
}

// --- detail drawer -----------------------------------------------------------

function UserDrawer({
  userId,
  canManage,
  onClose,
  onChanged,
}: {
  userId: string | null;
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const fetcher = useCallback(() => adminApi.getUser(userId as string), [userId]);
  const detail = useAdminResource(fetcher, userId !== null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleActive(activate: boolean) {
    if (!userId) return;
    setError(null);
    setBusy(true);
    const result = activate
      ? await adminApi.reactivateUser(userId)
      : await adminApi.deactivateUser(userId);
    setBusy(false);
    if (result.ok) {
      detail.reload();
      onChanged();
      return;
    }
    setError(result.error ?? "Couldn't update this user.");
  }

  async function changeStaffRole(value: string) {
    if (!userId) return;
    setError(null);
    setBusy(true);
    // "" from the selector means "revoke" → null. 422 (invalid name) / 400 (self) come
    // back as a normalized error string we surface inline; the server is the authority.
    const result = await adminApi.setStaffRole(userId, {
      staff_role: value === "" ? null : value,
    });
    setBusy(false);
    if (result.ok) {
      detail.reload();
      onChanged();
      return;
    }
    setError(result.error ?? "Couldn't change the staff role.");
  }

  const user = detail.data;

  return (
    <AdminDetailDrawer
      open={userId !== null}
      onClose={onClose}
      label={user ? `User: ${user.email}` : "User"}
    >
      {detail.loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !user ? (
        <p className="text-sm text-status-fail-fg">
          {detail.error ?? "Couldn't load this user."}
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">
                {user.name?.trim() || user.email}
              </h2>
              {user.is_active ? (
                <Badge level="pass">Active</Badge>
              ) : (
                <Badge level="neutral">Inactive</Badge>
              )}
            </div>
            <p className="mt-1 truncate font-mono text-[12.5px] text-status-neutral-solid">
              {user.email}
            </p>
            <p className="mt-0.5 text-[12px] text-marker">
              Joined {relativeTime(user.created_at)}
            </p>
          </div>

          {canManage ? (
            <div className="flex flex-col gap-4 rounded-lg border border-border-subtle bg-background p-4">
              <div>
                <label
                  htmlFor="staff-role"
                  className="mb-1.5 block text-[12px] font-medium text-foreground"
                >
                  Staff role
                </label>
                <select
                  id="staff-role"
                  disabled={busy}
                  value={user.staff_role ?? ""}
                  onChange={(event) => changeStaffRole(event.target.value)}
                  className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus-visible:border-accent focus-visible:outline-none disabled:opacity-50"
                >
                  <option value="">No staff role</option>
                  {STAFF_ROLES.map((role) => (
                    <option key={role} value={role}>
                      {humanizeRole(role)}
                    </option>
                  ))}
                </select>
                <p className="mt-1.5 text-[11.5px] text-status-neutral-solid">
                  You can&apos;t change your own staff role.
                </p>
              </div>

              <div>
                {user.is_active ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => toggleActive(false)}
                    className="border-status-fail-border text-status-fail-fg hover:bg-status-fail-bg"
                  >
                    {busy ? "Working…" : "Deactivate account"}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => toggleActive(true)}
                  >
                    {busy ? "Working…" : "Reactivate account"}
                  </Button>
                )}
              </div>

              {error ? (
                <p role="alert" className="text-xs text-status-fail-fg">
                  {error}
                </p>
              ) : null}
            </div>
          ) : null}

          <div>
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              Organizations
            </h3>
            {user.orgs.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">
                Not a member of any organization.
              </p>
            ) : (
              <div className="overflow-hidden rounded-lg border border-border">
                {user.orgs.map((org) => (
                  <div
                    key={org.org_id}
                    className="flex items-center gap-3 border-b border-border-subtle px-3.5 py-2.5 last:border-b-0"
                  >
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
                      {org.org_name}
                    </span>
                    <Badge level="neutral">{org.role}</Badge>
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

function ColHead({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
      {children}
    </span>
  );
}
