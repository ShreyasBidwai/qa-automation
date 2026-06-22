import { Activity, FolderGit2, LifeBuoy, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import { useIsActive } from "@/lib/router";
import { cn } from "@/lib/utils";

interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavEntry[] = [
  { to: "/projects", label: "Projects", icon: FolderGit2 },
  { to: "/runs", label: "Runs", icon: Activity },
];

function NavItem({ entry }: { entry: NavEntry }) {
  const active = useIsActive(entry.to);
  const Icon = entry.icon;
  return (
    <Link
      to={entry.to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm",
        active
          ? "bg-background font-medium text-accent"
          : "text-muted-foreground hover:bg-background hover:text-foreground",
      )}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      {entry.label}
    </Link>
  );
}

/** The persistent app shell: quiet left sidebar + content column. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface sm:flex">
        <div className="px-5 py-4">
          <Link to="/projects" aria-label="Polaris — home">
            <Wordmark />
          </Link>
        </div>
        <nav className="flex flex-col gap-0.5 px-3 py-2" aria-label="Primary">
          {NAV.map((entry) => (
            <NavItem key={entry.to} entry={entry} />
          ))}
        </nav>
        <nav className="mt-auto flex flex-col gap-0.5 px-3 py-2" aria-label="Support">
          <NavItem entry={{ to: "/help", label: "Help", icon: LifeBuoy }} />
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
