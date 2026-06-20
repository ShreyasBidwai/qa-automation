import type { ReactElement } from "react";

import { AppShell } from "@/components/AppShell";
import { NotFoundPage } from "@/components/NotFoundPage";
import { CreateProjectPage } from "@/features/projects/CreateProjectPage";
import { ProjectPage } from "@/features/projects/ProjectPage";
import { ProjectsListPage } from "@/features/projects/ProjectsListPage";
import { FindingsPlaceholder } from "@/features/runs/FindingsPlaceholder";
import { RunStatusPage } from "@/features/runs/RunStatusPage";
import { RunsListPage } from "@/features/runs/RunsListPage";
import { SystemStatusPage } from "@/features/system-status/SystemStatusPage";
import { useLocation } from "@/lib/router";

function renderRoute(pathname: string): ReactElement {
  const segments = pathname.replace(/\/+$/, "").split("/").filter(Boolean);

  if (segments.length === 0) return <ProjectsListPage />;

  if (segments[0] === "projects") {
    if (segments.length === 1) return <ProjectsListPage />;
    if (segments.length === 2 && segments[1] === "new") return <CreateProjectPage />;
    if (segments.length === 2) return <ProjectPage projectId={segments[1]} />;
  }

  if (segments[0] === "runs") {
    if (segments.length === 1) return <RunsListPage />;
    if (segments.length === 3 && segments[2] === "findings") {
      return <FindingsPlaceholder runId={segments[1]} />;
    }
    if (segments.length === 2) return <RunStatusPage runId={segments[1]} />;
  }

  if (segments[0] === "status") return <SystemStatusPage />;

  return <NotFoundPage />;
}

export function App() {
  const pathname = useLocation();
  return <AppShell>{renderRoute(pathname)}</AppShell>;
}
