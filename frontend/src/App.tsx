import { useEffect, type ReactElement } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthSplash } from "@/components/AuthSplash";
import { GenericErrorPage } from "@/components/GenericErrorPage";
import { NotFoundPage } from "@/components/NotFoundPage";
import { AdminAuditPage } from "@/features/admin/AdminAuditPage";
import { AdminFlywheelPage } from "@/features/admin/AdminFlywheelPage";
import { AdminIncidentsPage } from "@/features/admin/AdminIncidentsPage";
import { AdminJobsPage } from "@/features/admin/AdminJobsPage";
import { AdminOverviewPage } from "@/features/admin/AdminOverviewPage";
import { AdminTenantsPage } from "@/features/admin/AdminTenantsPage";
import { AdminUsersPage } from "@/features/admin/AdminUsersPage";
import { ConnectorPage } from "@/features/connectors/ConnectorPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ForgotPasswordPage } from "@/features/auth/ForgotPasswordPage";
import { SignInPage } from "@/features/auth/SignInPage";
import { SignUpPage } from "@/features/auth/SignUpPage";
import { AccountPage } from "@/features/account/AccountPage";
import { FindingsInboxPage } from "@/features/findings/FindingsInboxPage";
import { SingleFindingPage } from "@/features/findings/SingleFindingPage";
import { HelpCenterPage } from "@/features/help/HelpCenterPage";
import { PricingPage } from "@/features/pricing/PricingPage";
import { CreateProjectPage } from "@/features/projects/CreateProjectPage";
import { EditProjectPage } from "@/features/projects/EditProjectPage";
import { ProjectPage } from "@/features/projects/ProjectPage";
import { ProjectsListPage } from "@/features/projects/ProjectsListPage";
import { ProjectTestsPage } from "@/features/projects/ProjectTestsPage";
import { StartRunPage } from "@/features/projects/StartRunPage";
import { LiveRunView } from "@/features/runs/LiveRunView";
import { OngoingRunPage } from "@/features/runs/OngoingRunPage";
import { RunDashboard } from "@/features/runs/RunDashboard";
import { RunStatusPage } from "@/features/runs/RunStatusPage";
import { RunsListPage } from "@/features/runs/RunsListPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { SystemStatusPage } from "@/features/system-status/SystemStatusPage";
import { useAuth } from "@/lib/auth/useAuth";
import { useStaff } from "@/lib/auth/useStaff";
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

  // The account dashboard is the landing (ADR-0065); it hands off to Projects when the
  // account has no projects yet. `/dashboard` is its canonical URL.
  if (segments.length === 0) return <DashboardPage />;
  if (segments.length === 1 && segments[0] === "dashboard") return <DashboardPage />;

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
    if (segments.length === 3 && segments[2] === "tests") {
      return <ProjectTestsPage projectId={segments[1]} />;
    }
  }

  if (segments[0] === "runs") {
    if (segments.length === 1) return <RunsListPage />;
    // "ongoing" is reserved, matched before the `/runs/{id}` status route.
    if (segments.length === 2 && segments[1] === "ongoing") {
      return <OngoingRunPage />;
    }
    if (segments.length === 3 && segments[2] === "findings") {
      return <RunDashboard runId={segments[1]} />;
    }
    if (segments.length === 3 && segments[2] === "live") {
      return <LiveRunView runId={segments[1]} />;
    }
    if (segments.length === 2) return <RunStatusPage runId={segments[1]} />;
  }

  if (segments[0] === "connectors" && segments.length === 2) {
    if (segments[1] === "gitea") return <ConnectorPage kind="gitea" />;
    if (segments[1] === "pm") return <ConnectorPage kind="pm" />;
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

  // Customer-facing plans & pricing (B5) — reached discreetly from the account area,
  // deliberately kept off the main workflow nav.
  if (segments[0] === "pricing" && segments.length === 1) {
    return <PricingPage />;
  }

  // The operator/admin console (staff-only). Each page self-gates on the caller's
  // staff permission and renders a clean "not authorized" state for a non-staff user
  // (the server 403s regardless) — so a deep link here never crashes.
  if (segments[0] === "admin") {
    if (segments.length === 1) return <AdminOverviewPage />;
    if (segments.length === 2) {
      switch (segments[1]) {
        case "tenants":
          return <AdminTenantsPage />;
        case "users":
          return <AdminUsersPage />;
        case "jobs":
          return <AdminJobsPage />;
        case "incidents":
          return <AdminIncidentsPage />;
        case "flywheel":
          return <AdminFlywheelPage />;
        case "audit":
          return <AdminAuditPage />;
      }
    }
  }

  if (segments[0] === "settings" && segments.length === 1) {
    return <SettingsPage />;
  }

  if (segments[0] === "help" && segments.length === 1) return <HelpCenterPage />;

  if (segments[0] === "status") {
    // Full-height + own scroll (ADR-0066): the window never scrolls; the status page
    // scrolls its own body inside the app content region.
    return (
      <main className="h-full overflow-y-auto px-6 py-8">
        <div className="mx-auto max-w-[860px]">
          <SystemStatusPage />
        </div>
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
  const { staff } = useStaff();
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
      // Public (signed-out) status view renders straight into #root — give it its own
      // full-height scroll so the window never scrolls (ADR-0066).
      return (
        <main className="h-full overflow-y-auto px-6 py-8">
          <div className="mx-auto max-w-3xl">
            <SystemStatusPage />
          </div>
        </main>
      );
    }
    return standalone ?? <SignInPage />;
  }

  // Signed in: bounce away from the auth pages, otherwise render the app.
  if (AUTH_PATHS.has(clean)) return <NavigateTo to="/" />;
  if (clean === "/error") return <GenericErrorPage />;
  // Staff are platform operators: land them on the console, not the customer dashboard.
  if (staff && (clean === "/" || clean === "/dashboard")) {
    return <NavigateTo to="/admin" />;
  }
  return <AppShell>{renderRoute(pathname)}</AppShell>;
}
