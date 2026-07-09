import {
  AlertTriangle,
  Building2,
  ClipboardList,
  FolderGit2,
  GitBranch,
  HelpCircle,
  Inbox,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Radio,
  ScrollText,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  Sun,
  User,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { CommandPalette } from "@/components/CommandPalette";
import { Drawer } from "@/components/Drawer";
import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import { useRunLifecycleToasts } from "@/features/runs/useRunLifecycleToasts";
import type { AuthUser, StaffPermission } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { useStaff } from "@/lib/auth/useStaff";
import { useLocation } from "@/lib/router";
import { useTheme } from "@/lib/theme/useTheme";
import { cn } from "@/lib/utils";

interface NavEntry {
  to: string;
  label: string;
  // The same icon each destination already shows next to its own page title (or,
  // for pages with no title icon yet, the closest thematic match already in use
  // there) — the sidebar mirrors the page instead of inventing a second icon set.
  icon: LucideIcon;
}

/** An admin nav entry, plus the staff permission that reveals it. The server is the
 *  real authority; hiding the tab just avoids offering an action it would refuse. */
interface AdminNavEntry extends NavEntry {
  perm: StaffPermission;
}

// Order lifted from the sidebar in Polaris Account.dc.html / Run Dashboard.dc.html.
// Dashboard is the account landing (ADR-0065) and leads the nav.
const PRIMARY: NavEntry[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/projects", label: "Projects", icon: FolderGit2 },
  { to: "/findings", label: "Findings", icon: Inbox },
  { to: "/runs/ongoing", label: "Ongoing run", icon: Radio },
  { to: "/runs", label: "Runs", icon: ListChecks },
];

// Connectors get their own sidebar tabs (Gitea + PM tool) — roadmap integrations,
// each a real destination that explains itself. Kept apart from the workflow nav.
const CONNECTORS: NavEntry[] = [
  { to: "/connectors/gitea", label: "Gitea", icon: GitBranch },
  { to: "/connectors/pm", label: "PM tool", icon: ClipboardList },
];

// The operator/admin console — its own section, shown ONLY to staff (each entry
// further gated by the permission it needs). Ordered overview → tenants/users →
// operational (queue/incidents) → audit, so the console reads top-down.
const ADMIN: AdminNavEntry[] = [
  { to: "/admin", label: "Overview", icon: ShieldCheck, perm: "view_ops" },
  { to: "/admin/tenants", label: "Tenants", icon: Building2, perm: "view_tenants" },
  { to: "/admin/users", label: "Users", icon: Users, perm: "view_users" },
  { to: "/admin/jobs", label: "Queue", icon: ListChecks, perm: "view_ops" },
  { to: "/admin/incidents", label: "Incidents", icon: AlertTriangle, perm: "view_ops" },
  { to: "/admin/flywheel", label: "Flywheel", icon: Sparkles, perm: "view_ops" },
  { to: "/admin/audit", label: "Audit", icon: ScrollText, perm: "view_audit" },
];

// The quiet bottom cluster (Settings is pinned bottom in the file; we keep our
// account/settings/help set).
const SECONDARY: NavEntry[] = [
  { to: "/account", label: "Account", icon: Users },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
  { to: "/help", label: "Help", icon: HelpCircle },
];

/** Does `to` match `pathname` (exact, or a parent segment prefix)? */
function matchesNav(pathname: string, to: string): boolean {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}

/** The single best-matching nav target — the LONGEST matching prefix — so a deeper
 *  route (e.g. `/runs/ongoing`) lights only its own entry, never also a shallower one
 *  (`/runs`), while `/runs/{id}` still lights "Runs". */
function activeNavTarget(pathname: string, entries: NavEntry[]): string | null {
  const clean = pathname.replace(/\/+$/, "") || "/";
  let best: string | null = null;
  for (const entry of entries) {
    if (
      matchesNav(clean, entry.to) &&
      (best === null || entry.to.length > best.length)
    ) {
      best = entry.to;
    }
  }
  return best;
}

function NavItem({
  entry,
  active,
  muted,
}: {
  entry: NavEntry;
  active: boolean;
  muted?: boolean;
}) {
  return (
    <Link
      to={entry.to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-sm",
        active
          ? "bg-accent-subtle font-semibold text-accent"
          : cn(
              "font-medium hover:bg-background hover:text-foreground",
              muted ? "text-muted-foreground" : "text-status-neutral-fg",
            ),
      )}
    >
      {/* The tab's own title icon — colour rides the link's text colour
          (currentColor), so active/idle/muted stay a single source of truth. */}
      <entry.icon className="h-[15px] w-[15px] shrink-0" aria-hidden="true" />
      {entry.label}
    </Link>
  );
}

/** A simple sign-out action styled like the muted account-cluster items. Clears the
 * session via the auth context; App's guard then redirects to /login. */
function SignOutButton() {
  const { signOut } = useAuth();
  return (
    <button
      type="button"
      onClick={() => void signOut()}
      className="flex items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-left text-sm font-medium text-muted-foreground hover:bg-background hover:text-foreground"
    >
      <LogOut className="h-[14px] w-[14px] shrink-0" aria-hidden="true" />
      Sign out
    </button>
  );
}

/** The PRIMARY/CONNECTORS/SECONDARY nav groups — the single source both the desktop
 *  sidebar and the mobile drawer render, so the two surfaces can never drift. */
function SidebarNav({ activeTarget }: { activeTarget: string | null }) {
  const { staff, hasPerm } = useStaff();
  const isStaff = staff !== null;
  // Staff are PLATFORM OPERATORS, not customers: the nav IS the operator console — no
  // create/test workflow or connectors (to see a customer's view they impersonate,
  // ADR-0071). Each admin tab is still gated by its permission, so a billing-only
  // staffer never sees Tenants. Customers get the workflow + connectors and never see
  // /admin. Shared by the desktop sidebar + mobile drawer so the two can't drift.
  const primary = isStaff ? ADMIN.filter((entry) => hasPerm(entry.perm)) : PRIMARY;
  return (
    <>
      <nav
        className="flex flex-col gap-0.5"
        aria-label={isStaff ? "Operator console" : "Primary"}
      >
        {primary.map((entry) => (
          <NavItem key={entry.to} entry={entry} active={entry.to === activeTarget} />
        ))}
      </nav>
      {!isStaff && (
        <nav
          className="mt-4 flex flex-col gap-0.5 border-t border-border-subtle pt-3"
          aria-label="Connectors"
        >
          <p className="px-2.5 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-marker">
            Connectors
          </p>
          {CONNECTORS.map((entry) => (
            <NavItem
              key={entry.to}
              entry={entry}
              active={entry.to === activeTarget}
              muted
            />
          ))}
        </nav>
      )}
      <nav
        className="mt-auto flex flex-col gap-0.5 border-t border-border-subtle pt-3"
        aria-label="Account and support"
      >
        {SECONDARY.map((entry) => (
          <NavItem
            key={entry.to}
            entry={entry}
            active={entry.to === activeTarget}
            muted
          />
        ))}
        <SignOutButton />
      </nav>
    </>
  );
}

/** The sidebar nav in an overlay drawer for narrow viewports (< sm), where there is
 *  no room for the persistent sidebar. Reuses `SidebarNav` verbatim — same entries,
 *  same active-state logic — so mobile can never show a different nav than desktop.
 *  Closes on Esc / a backdrop click (Drawer) and on route change (AppShell effect). */
function MobileNavDrawer({
  open,
  onClose,
  activeTarget,
}: {
  open: boolean;
  onClose: () => void;
  activeTarget: string | null;
}) {
  return (
    <Drawer open={open} onClose={onClose} label="Navigation">
      <div className="flex h-full flex-col px-3.5 py-5">
        <div className="flex items-center justify-between px-2.5 pb-[22px] pt-1.5">
          <Wordmark className="text-[18px]" />
          <button
            type="button"
            data-autofocus
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground hover:bg-background"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <SidebarNav activeTarget={activeTarget} />
      </div>
    </Drawer>
  );
}

/** ⌘K (macOS) / Ctrl+K (elsewhere) opens the command palette from anywhere in the
 *  shell — not just while the search box has focus (ADR-0072). */
function useCommandPaletteShortcut(onTrigger: () => void): void {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onTrigger();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onTrigger]);
}

/**
 * The persistent app shell (Polaris Account.dc.html / Run Dashboard.dc.html): a
 * 232px white sidebar — wordmark · Projects/Findings/Runs · a bottom
 * account/settings/help cluster above a subtle divider — and a 56px top bar over
 * a single scrolling content column.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useLocation();
  const { staff, hasPerm } = useStaff();
  const isStaff = staff !== null;
  // Staff are PLATFORM OPERATORS, not customers: the sidebar IS the operator console —
  // no create/test workflow (they never build/run projects; to see a customer's view
  // they impersonate, ADR-0071). Each admin tab is still gated by its permission, so a
  // billing-only staffer never sees Tenants. Customers get the workflow + connectors and
  // never see /admin.
  const primary = isStaff ? ADMIN.filter((entry) => hasPerm(entry.perm)) : PRIMARY;
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  useCommandPaletteShortcut(() => setPaletteOpen(true));
  // App-wide "a run finished" toast (mission item 3) — mounted once here so it
  // keeps announcing regardless of which page the operator is currently on.
  useRunLifecycleToasts();
  // A route change is the clearest "the user is done with the drawer" signal — close
  // it automatically rather than leaving it open over the new page.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);
  // Resolve the active entry ONCE across every VISIBLE nav target, so only the longest
  // match lights up (no double-highlight of "Runs" + "Ongoing run" on /runs/ongoing).
  const activeTarget = activeNavTarget(pathname, [
    ...primary,
    ...(isStaff ? [] : CONNECTORS),
    ...SECONDARY,
  ]);
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <aside className="hidden w-[232px] shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5 sm:flex">
        <div className="px-2.5 pb-[22px] pt-1.5">
          <Link to="/" aria-label="Polaris — home">
            <Wordmark className="text-[18px]" />
          </Link>
        </div>
        <SidebarNav activeTarget={activeTarget} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          onOpenSearch={() => setPaletteOpen(true)}
          onOpenNav={() => setMobileNavOpen(true)}
        />
        {/* The content region is a bounded frame, not a page that scrolls (ADR-0066):
            each view is full-height and scrolls its own body/sections. `overflow-y-auto`
            is a safety net (a view that isn't height-managed degrades to a contained
            scroll here rather than clipping) — it should not show in practice. */}
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <MobileNavDrawer
        open={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        activeTarget={activeTarget}
      />
    </div>
  );
}

function TopBar({
  onOpenSearch,
  onOpenNav,
}: {
  onOpenSearch: () => void;
  onOpenNav: () => void;
}) {
  const pathname = useLocation();
  const { user, signOut } = useAuth();
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 sm:px-6">
      <div className="flex items-center gap-2.5">
        {/* Below `sm` there is no persistent sidebar (AppShell) — this is the ONLY
            way to reach navigation, so it's a real gap without it, not polish. */}
        <button
          type="button"
          onClick={onOpenNav}
          aria-label="Open navigation"
          className="-ml-1.5 rounded-md p-1.5 text-muted-foreground hover:bg-background hover:text-foreground sm:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
        {/* Mobile: the wordmark (no sidebar). Desktop: the current section context. */}
        <Link to="/" aria-label="Polaris — home" className="sm:hidden">
          <Wordmark className="text-[18px]" />
        </Link>
      </div>
      <span className="hidden text-sm font-semibold text-foreground sm:block">
        {sectionLabel(pathname)}
      </span>

      <div className="flex items-center gap-3.5">
        <button
          type="button"
          onClick={onOpenSearch}
          className="hidden h-8 w-[240px] items-center gap-2 rounded-lg border border-border bg-background px-[11px] text-[13px] text-status-neutral-solid hover:border-marker hover:text-foreground md:flex"
        >
          <Search className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="flex-1 text-left">Search findings…</span>
          <kbd className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-marker">
            ⌘K
          </kbd>
        </button>
        <ThemeToggle />
        <Link
          to="/account"
          aria-label="Your account"
          className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground"
        >
          {initialsOf(user) || <User className="h-4 w-4" aria-hidden="true" />}
        </Link>
        {/* Always-visible sign-out — the sidebar's sits at the bottom and can fall below
            the fold; logout should never be a hunt. */}
        <button
          type="button"
          onClick={() => void signOut()}
          aria-label="Sign out"
          title="Sign out"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border text-status-neutral-solid hover:bg-background hover:text-foreground"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

/** Quick-access light/dark toggle (ADR-0073) — also lives in Settings as the fuller,
 *  labeled control; this is the always-in-reach one. */
function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground"
    >
      {isDark ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}

/** The current section, for the top-bar context label (route-derived, real). */
function sectionLabel(pathname: string): string {
  const segment = pathname.replace(/\/+$/, "").split("/").filter(Boolean)[0] ?? "";
  switch (segment) {
    case "":
    case "dashboard":
      return "Dashboard";
    case "projects":
      return "Projects";
    case "findings":
      return "Findings";
    case "runs":
      return "Runs";
    case "connectors":
      return "Connectors";
    case "admin":
      return "Admin";
    case "account":
      return "Account";
    case "pricing":
      return "Plans & pricing";
    case "settings":
      return "Settings";
    case "help":
      return "Help";
    case "status":
      return "System status";
    default:
      return "Polaris";
  }
}

/** Two-letter initials from the signed-in user (name, else email). */
function initialsOf(user: AuthUser | null): string {
  if (!user) return "";
  const name = user.name?.trim();
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return user.email.slice(0, 2).toUpperCase();
}
