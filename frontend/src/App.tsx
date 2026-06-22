import type { ReactElement } from "react";

import { AppShell } from "@/components/AppShell";
import { GenericErrorPage } from "@/components/GenericErrorPage";
import { NotFoundPage } from "@/components/NotFoundPage";
import { ForgotPasswordPage } from "@/features/auth/ForgotPasswordPage";
import { SignInPage } from "@/features/auth/SignInPage";
import { SignUpPage } from "@/features/auth/SignUpPage";
import { FindingsInboxPage } from "@/features/findings/FindingsInboxPage";
import { HelpCenterPage } from "@/features/help/HelpCenterPage";
import { PlaceholderPage } from "@/features/placeholders/PlaceholderPage";
import { CreateProjectPage } from "@/features/projects/CreateProjectPage";
import { EditProjectPage } from "@/features/projects/EditProjectPage";
import { ProjectPage } from "@/features/projects/ProjectPage";
import { ProjectsListPage } from "@/features/projects/ProjectsListPage";
import { StartRunPage } from "@/features/projects/StartRunPage";
import { RunDashboard } from "@/features/runs/RunDashboard";
import { RunStatusPage } from "@/features/runs/RunStatusPage";
import { RunsListPage } from "@/features/runs/RunsListPage";
import { SystemStatusPage } from "@/features/system-status/SystemStatusPage";
import { useLocation } from "@/lib/router";

/** Full-screen routes that render outside the app shell (no sidebar). */
function renderStandaloneRoute(pathname: string): ReactElement | null {
  switch (pathname.replace(/\/+$/, "")) {
    case "/login":
      return <SignInPage />;
    case "/signup":
      return <SignUpPage />;
    case "/forgot":
      return <ForgotPasswordPage />;
    case "/error":
      return <GenericErrorPage />;
    default:
      return null;
  }
}

function renderRoute(pathname: string): ReactElement {
  const segments = pathname.replace(/\/+$/, "").split("/").filter(Boolean);

  if (segments.length === 0) return <ProjectsListPage />;

  if (segments[0] === "projects") {
    if (segments.length === 1) return <ProjectsListPage />;
    if (segments.length === 2 && segments[1] === "new") return <CreateProjectPage />;
    if (segments.length === 2) return <ProjectPage projectId={segments[1]} />;
    if (segments.length === 3 && segments[2] === "edit") {
      return <EditProjectPage projectId={segments[1]} />;
    }
    if (segments.length === 3 && segments[2] === "run") {
      return <StartRunPage projectId={segments[1]} />;
    }
  }

  if (segments[0] === "runs") {
    if (segments.length === 1) return <RunsListPage />;
    if (segments.length === 3 && segments[2] === "findings") {
      return <RunDashboard runId={segments[1]} />;
    }
    if (segments.length === 2) return <RunStatusPage runId={segments[1]} />;
  }

  if (segments[0] === "findings" && segments.length === 1) {
    return <FindingsInboxPage />;
  }

  if (segments[0] === "account" && segments.length === 1) {
    return (
      <PlaceholderPage
        title="Account"
        description="Your profile and team settings arrive with sign-in in a later slice."
      />
    );
  }

  if (segments[0] === "settings" && segments.length === 1) {
    return (
      <PlaceholderPage
        title="Settings"
        description="Workspace settings arrive in a later slice."
      />
    );
  }

  if (segments[0] === "help" && segments.length === 1) return <HelpCenterPage />;

  if (segments[0] === "status") return <SystemStatusPage />;

  return <NotFoundPage />;
}

export function App() {
  const pathname = useLocation();
  const standalone = renderStandaloneRoute(pathname);
  if (standalone) return standalone;
  return <AppShell>{renderRoute(pathname)}</AppShell>;
}
