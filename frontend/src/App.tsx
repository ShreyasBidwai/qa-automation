import { useEffect, type ReactElement } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthSplash } from "@/components/AuthSplash";
import { GenericErrorPage } from "@/components/GenericErrorPage";
import { NotFoundPage } from "@/components/NotFoundPage";
import { ForgotPasswordPage } from "@/features/auth/ForgotPasswordPage";
import { SignInPage } from "@/features/auth/SignInPage";
import { SignUpPage } from "@/features/auth/SignUpPage";
import { AccountPage } from "@/features/account/AccountPage";
import { FindingsInboxPage } from "@/features/findings/FindingsInboxPage";
import { SingleFindingPage } from "@/features/findings/SingleFindingPage";
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
import { useAuth } from "@/lib/auth/useAuth";
import { navigate, useLocation } from "@/lib/router";

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

  if (segments[0] === "findings" && segments.length === 2) {
    return <SingleFindingPage findingId={segments[1]} />;
  }

  if (segments[0] === "account" && segments.length === 1) {
    return <AccountPage />;
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

  if (segments[0] === "status") {
    // In-shell the status page carried no page gutters (it rendered flush to the
    // top bar and sidebar); give it the same balanced container the other screens use.
    return (
      <main className="mx-auto max-w-[860px] px-6 py-8">
        <SystemStatusPage />
      </main>
    );
  }

  return <NotFoundPage />;
}

const AUTH_PATHS = new Set(["/login", "/signup", "/forgot"]);

/** Navigate on mount, then hold a splash until the route swap re-renders App. */
function NavigateTo({ to }: { to: string }) {
  useEffect(() => {
    navigate(to);
  }, [to]);
  return <AuthSplash />;
}

export function App() {
  const { status } = useAuth();
  const pathname = useLocation();
  const clean = pathname.replace(/\/+$/, "") || "/";

  // Still checking the persisted session — hold a calm splash.
  if (status === "loading") return <AuthSplash />;

  const standalone = renderStandaloneRoute(pathname);

  // Signed out: the public front-door pages and the public system-status view
  // render; any other route falls back to sign-in (in place, so the deep link is
  // preserved through login).
  if (status === "anonymous") {
    if (clean === "/status") {
      return (
        <main className="mx-auto max-w-3xl px-6 py-8">
          <SystemStatusPage />
        </main>
      );
    }
    return standalone ?? <SignInPage />;
  }

  // Signed in: bounce away from the auth pages, otherwise render the app.
  if (AUTH_PATHS.has(clean)) return <NavigateTo to="/" />;
  if (clean === "/error") return <GenericErrorPage />;
  return <AppShell>{renderRoute(pathname)}</AppShell>;
}
