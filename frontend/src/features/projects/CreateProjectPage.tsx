import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";

import { CreateProjectForm } from "./CreateProjectForm";

/** New project (#3): connect a codebase and a running environment. */
export function CreateProjectPage() {
  return (
    <PageShell scroll={false} maxWidth="max-w-[760px]">
      {/* Back-link + title stay put (ADR-0066); the form body scrolls on its own. */}
      <div className="shrink-0">
        <Link
          to="/projects"
          className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        >
          ← Projects
        </Link>
        <div className="mb-7 mt-3">
          <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
            New project
          </h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
            Connect a codebase and a running environment. Polaris reads the repo, maps
            the app, and starts finding problems.
          </p>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <CreateProjectForm />
      </div>
    </PageShell>
  );
}
