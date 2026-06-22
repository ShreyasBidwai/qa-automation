import { Search, User } from "lucide-react";
import type { ReactNode } from "react";

import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import type { AuthUser } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { useIsActive, useLocation } from "@/lib/router";
import { cn } from "@/lib/utils";

interface NavEntry {
  to: string;
  label: string;
}

// Order lifted from the sidebar in Polaris Account.dc.html / Run Dashboard.dc.html.
const PRIMARY: NavEntry[] = [
  { to: "/projects", label: "Projects" },
  { to: "/findings", label: "Findings" },
  { to: "/runs", label: "Runs" },
];

// The quiet bottom cluster (Settings is pinned bottom in the file; we keep our
// account/settings/help set).
const SECONDARY: NavEntry[] = [
  { to: "/account", label: "Account" },
  { to: "/settings", label: "Settings" },
  { to: "/help", label: "Help" },
];

function NavItem({ entry, muted }: { entry: NavEntry; muted?: boolean }) {
  const active = useIsActive(entry.to);
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
      {/* 7px square dot marker — filled indigo when active, idle grey otherwise. */}
      <span
        aria-hidden="true"
        className={cn(
          "h-[7px] w-[7px] shrink-0 rounded-[2px]",
          active ? "bg-accent" : "bg-marker",
        )}
      />
      {entry.label}
    </Link>
  );
}

/**
 * The persistent app shell (Polaris Account.dc.html / Run Dashboard.dc.html): a
 * 232px white sidebar — wordmark · Projects/Findings/Runs · a bottom
 * account/settings/help cluster above a subtle divider — and a 56px top bar over
 * a single scrolling content column.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <aside className="hidden w-[232px] shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5 sm:flex">
        <div className="px-2.5 pb-[22px] pt-1.5">
          <Link to="/" aria-label="Polaris — home">
            <Wordmark className="text-[18px]" />
          </Link>
        </div>
        <nav className="flex flex-col gap-0.5" aria-label="Primary">
          {PRIMARY.map((entry) => (
            <NavItem key={entry.to} entry={entry} />
          ))}
        </nav>
        <nav
          className="mt-auto flex flex-col gap-0.5 border-t border-border-subtle pt-3"
          aria-label="Account and support"
        >
          {SECONDARY.map((entry) => (
            <NavItem key={entry.to} entry={entry} muted />
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

function TopBar() {
  const pathname = useLocation();
  const { user } = useAuth();
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 sm:px-6">
      {/* Mobile: the wordmark (no sidebar). Desktop: the current section context. */}
      <Link to="/" aria-label="Polaris — home" className="sm:hidden">
        <Wordmark className="text-[18px]" />
      </Link>
      <span className="hidden text-sm font-semibold text-foreground sm:block">
        {sectionLabel(pathname)}
      </span>

      <div className="flex items-center gap-3.5">
        {/* Search affordance per the design — global search isn't wired yet. */}
        <button
          type="button"
          disabled
          title="Search is coming in a later slice"
          className="hidden h-8 w-[240px] cursor-default items-center gap-2 rounded-lg border border-border bg-background px-[11px] text-[13px] text-status-neutral-solid md:flex"
        >
          <Search className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Search findings…</span>
        </button>
        <Link
          to="/account"
          aria-label="Your account"
          className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground"
        >
          {initialsOf(user) || <User className="h-4 w-4" aria-hidden="true" />}
        </Link>
      </div>
    </header>
  );
}

/** The current section, for the top-bar context label (route-derived, real). */
function sectionLabel(pathname: string): string {
  const segment = pathname.replace(/\/+$/, "").split("/").filter(Boolean)[0] ?? "";
  switch (segment) {
    case "":
    case "projects":
      return "Projects";
    case "findings":
      return "Findings";
    case "runs":
      return "Runs";
    case "account":
      return "Account";
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
