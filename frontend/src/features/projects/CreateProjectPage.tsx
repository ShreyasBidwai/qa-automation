import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";

import { CreateProjectForm } from "./CreateProjectForm";

/** New project (#3): connect a codebase and a running environment. */
export function CreateProjectPage() {
  return (
    <PageShell maxWidth="max-w-[760px]">
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
          Connect a codebase and a running environment. Polaris reads the repo, maps the
          app, and starts finding problems.
        </p>
      </div>
      <CreateProjectForm />
    </PageShell>
  );
}
