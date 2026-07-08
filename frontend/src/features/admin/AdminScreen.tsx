import { ShieldOff, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { PageShell } from "@/components/PageShell";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import type { StaffPermission } from "@/lib/api/types";
import { useStaff } from "@/lib/auth/useStaff";

/** The shared admin page header — the bordered title icon + title/subtitle used across
 *  the app's pages, with an optional right-aligned actions slot. */
export function AdminHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-marker">
          <Icon className="h-4 w-4 text-status-neutral-solid" aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-0.5 text-[13px] text-status-neutral-solid">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {actions}
    </div>
  );
}

/** The honest "no access" state for a non-staff caller (or one missing the permission).
 *  The server is authoritative — it 403s regardless; this just avoids a dead screen. */
export function NotAuthorized() {
  return (
    <StatePanel
      icon={ShieldOff}
      title="You don't have access to this area"
      description="The operator console is limited to Polaris staff. If you think this is a mistake, ask an administrator to grant you a staff role."
    />
  );
}

/**
 * The frame every admin page renders inside (ADR-0066: full-height, the window never
 * scrolls). It resolves the caller's staff identity once and gates the body:
 *  - while the identity is loading → a calm skeleton,
 *  - not staff / missing `perm` → the NotAuthorized state,
 *  - otherwise → the page body (which only mounts, and only fetches, when authorized).
 *
 * `scroll` mirrors PageShell: `false` (default) contains the body to the viewport so a
 * table/list scrolls in-section; `true` lets a short page (the overview) scroll as one.
 */
export function AdminScreen({
  icon,
  title,
  subtitle,
  perm,
  actions,
  scroll = false,
  children,
}: {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  perm: StaffPermission;
  actions?: ReactNode;
  scroll?: boolean;
  children: ReactNode;
}) {
  const { loading, staff, hasPerm } = useStaff();
  const allowed = !loading && staff !== null && hasPerm(perm);
  return (
    <PageShell
      scroll={scroll}
      header={
        <AdminHeader
          icon={icon}
          title={title}
          subtitle={subtitle}
          actions={allowed ? actions : undefined}
        />
      }
    >
      {loading ? (
        <SkeletonRows label="Checking access…" />
      ) : allowed ? (
        children
      ) : (
        <NotAuthorized />
      )}
    </PageShell>
  );
}
