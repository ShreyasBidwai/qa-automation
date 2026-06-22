import { Search, User } from "lucide-react";
import type { ReactNode } from "react";

import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import { useIsActive } from "@/lib/router";
import { cn } from "@/lib/utils";

interface NavEntry {
  to: string;
  label: string;
}

// Primary destinations (design brief app shell). Findings is the global inbox
// (a later slice); Projects + Runs are live.
const PRIMARY: NavEntry[] = [
  { to: "/findings", label: "Findings" },
  { to: "/projects", label: "Projects" },
  { to: "/runs", label: "Runs" },
];

// The quiet bottom cluster: account / settings / help.
const SECONDARY: NavEntry[] = [
  { to: "/account", label: "Account" },
  { to: "/settings", label: "Settings" },
  { to: "/help", label: "Help" },
];

function NavItem({ entry }: { entry: NavEntry }) {
  const active = useIsActive(entry.to);
  return (
    <Link
      to={entry.to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
        active
          ? "bg-accent-subtle font-semibold text-accent"
          : "font-medium text-status-neutral-fg hover:bg-background hover:text-foreground",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-[7px] w-[7px] shrink-0 rounded-[2px]",
          active ? "bg-accent" : "bg-status-neutral-solid",
        )}
      />
      {entry.label}
    </Link>
  );
}

/**
 * The persistent app shell: a quiet fixed sidebar (wordmark · primary nav ·
 * bottom account/settings/help cluster) and a top bar over a single scrolling
 * content column. Light, hairline-bordered, unobtrusive (design brief).
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-5 sm:flex">
        <div className="px-2.5 pb-5">
          <Link to="/" aria-label="Polaris — home">
            <Wordmark />
          </Link>
        </div>
        <nav className="flex flex-col gap-0.5" aria-label="Primary">
          {PRIMARY.map((entry) => (
            <NavItem key={entry.to} entry={entry} />
          ))}
        </nav>
        <nav
          className="mt-auto flex flex-col gap-0.5 border-t border-border pt-3"
          aria-label="Account and support"
        >
          {SECONDARY.map((entry) => (
            <NavItem key={entry.to} entry={entry} />
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
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 sm:px-6">
      {/* The wordmark shows on mobile, where the sidebar is hidden. */}
      <Link to="/" aria-label="Polaris — home" className="sm:hidden">
        <Wordmark />
      </Link>
      <div className="hidden sm:block" />
      <div className="flex items-center gap-3">
        {/* Global search is a later slice — present but clearly not yet wired. */}
        <button
          type="button"
          disabled
          title="Global search is coming in a later slice"
          className="hidden h-8 cursor-default items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm text-muted-foreground sm:flex"
        >
          <Search className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Search findings…</span>
        </button>
        <Link
          to="/account"
          aria-label="Account"
          className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-background text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <User className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </header>
  );
}
