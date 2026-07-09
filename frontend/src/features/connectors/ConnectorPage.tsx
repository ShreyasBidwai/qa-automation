import { ClipboardList, GitBranch, type LucideIcon } from "lucide-react";

import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";
import { Button } from "@/components/ui/button";

/** Kinds of connector the sidebar exposes. */
export type ConnectorKind = "gitea" | "pm";

interface ConnectorSpec {
  name: string;
  tagline: string;
  icon: LucideIcon;
  capabilities: string[];
}

// Roadmap connectors. Surfaced now (clearly "coming soon", never a dead link or a
// fake screen) so operators know they're planned. Static/frontend-only — there is no
// backend, no credential field, and nothing is sent anywhere until each ships.
const CONNECTORS: Record<ConnectorKind, ConnectorSpec> = {
  gitea: {
    name: "Gitea",
    tagline: "Self-hosted git host — ingest repos and open PRs with findings.",
    icon: GitBranch,
    capabilities: [
      "Ingest a target codebase straight from a Gitea repository.",
      "Open a pull request carrying the tests Polaris authored.",
      "Post a run's gate verdict back as a PR status check.",
    ],
  },
  pm: {
    name: "PM tool",
    tagline: "Push findings into your project tracker (Jira, Linear, …).",
    icon: ClipboardList,
    capabilities: [
      "Open a tracker issue from a confirmed finding.",
      "Keep issue status in sync as a finding heals or regresses.",
      "Link every issue back to the run that surfaced it.",
    ],
  },
};

/**
 * A connector's own page (Gitea / PM tool) — a sidebar destination that describes
 * what the integration will do, marked honestly as not-yet-built. No credentials are
 * collected here; when a connector ships, secrets go to the encrypted vault (ADR-0053),
 * never the client.
 */
export function ConnectorPage({ kind }: { kind: ConnectorKind }) {
  const spec = CONNECTORS[kind];
  return (
    <PageShell maxWidth="max-w-[860px]">
      <header className="flex items-start gap-3.5">
        <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl border-[1.5px] border-marker">
          <spec.icon
            className="h-[18px] w-[18px] text-status-neutral-solid"
            aria-hidden="true"
          />
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-foreground">
              {spec.name}
            </h1>
            <span className="rounded-full bg-status-neutral-bg px-2 py-0.5 text-[11px] font-medium text-status-neutral-fg">
              Coming soon
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{spec.tagline}</p>
        </div>
      </header>

      <section className="mt-7 rounded-xl border border-dashed border-border bg-surface p-6 shadow-card">
        <h2 className="text-sm font-semibold text-foreground">
          What this connector will do
        </h2>
        <ul className="mt-3 space-y-2.5">
          {spec.capabilities.map((capability) => (
            <li
              key={capability}
              className="flex items-start gap-2.5 text-[13.5px] text-foreground-secondary"
            >
              <span
                className="mt-[7px] h-[6px] w-[6px] shrink-0 rounded-full bg-marker"
                aria-hidden="true"
              />
              {capability}
            </li>
          ))}
        </ul>
        <p className="mt-5 text-xs text-muted-foreground">
          Not wired up yet — this lands in a later slice. Credentials will live in the
          encrypted vault, never in the browser.
        </p>
      </section>

      <div className="mt-6">
        <Button variant="outline" asChild>
          <Link to="/projects">Back to projects</Link>
        </Button>
      </div>
    </PageShell>
  );
}
