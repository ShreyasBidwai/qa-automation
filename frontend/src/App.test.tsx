import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  authApi: {
    me: vi.fn(),
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    updateProfile: vi.fn(),
  },
  projectApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    ingest: vi.fn(),
  },
  findingApi: { listOpen: vi.fn(), listForProject: vi.fn() },
  runApi: {
    list: vi.fn(),
    get: vi.fn(),
    findings: vi.fn(),
    create: vi.fn(),
    triage: vi.fn(),
    active: vi.fn(),
  },
  jobApi: { get: vi.fn() },
  healthApi: { liveness: vi.fn(), readiness: vi.fn() },
  accountApi: { dashboard: vi.fn() },
  // The app shell asks /admin/me (via useStaff); default to "not staff" so the
  // authenticated routes render without the Admin nav (and without a crash).
  adminApi: {
    me: vi.fn(() => Promise.resolve({ ok: false, status: 403, data: null })),
  },
  searchApi: { search: vi.fn() },
}));

import {
  accountApi,
  adminApi,
  authApi,
  healthApi,
  projectApi,
  runApi,
} from "@/lib/api/client";
import { ToastProvider } from "@/components/ToastProvider";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken, setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";

import { App } from "./App";

function renderApp() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe("App auth gating", () => {
  beforeEach(() => {
    clearToken();
    resetStaffCache();
    vi.clearAllMocks();
    // Re-arm the default "not staff" reply after clearAllMocks wiped call state.
    vi.mocked(adminApi.me).mockResolvedValue({ ok: false, status: 403, data: null });
    window.history.pushState({}, "", "/");
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    // useRunLifecycleToasts (mounted inside AppShell) polls this on mount.
    vi.mocked(runApi.active).mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: null, project_id: null, mode: null, status: null },
    });
  });

  it("sends an unauthenticated visitor to sign in (no app data shown)", async () => {
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Sign in to Polaris" }),
    ).toBeInTheDocument();
    // The protected projects data is never requested while signed out.
    expect(projectApi.list).not.toHaveBeenCalled();
  });

  it("loads the account dashboard once authenticated", async () => {
    setToken("tok-1");
    vi.mocked(authApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01" },
    });
    // Root is the account Dashboard (ADR-0065); it renders for an account with projects.
    vi.mocked(accountApi.dashboard).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        range_days: 30,
        projects_total: 1,
        projects_by_status: { passing: 1 },
        open_findings: { critical: 0, major: 0, minor: 0, total: 0 },
        project_health: [
          {
            project_id: "p1",
            name: "Acme",
            status: "passing",
            pass_rate: 1,
            open_findings: 0,
            last_run_at: null,
          },
        ],
        runs_total: 0,
        tests_total: 0,
        outcomes: { pass: 0, fail: 0, error: 0, skipped: 0 },
        pass_rate: null,
        trend: [],
        recent_runs: [],
      },
    });

    renderApp();

    // The real app renders (not the sign-in front door): the Dashboard heading + data.
    expect(
      await screen.findByRole("heading", { name: "Dashboard" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in to Polaris" })).toBeNull();
    expect(accountApi.dashboard).toHaveBeenCalled();
  });

  it("renders the in-shell 404 for an authenticated unknown path", async () => {
    setToken("tok-1");
    vi.mocked(authApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01" },
    });
    window.history.pushState({}, "", "/no/such/route");

    renderApp();

    expect(
      await screen.findByRole("heading", { name: "This page doesn't exist" }),
    ).toBeInTheDocument();
    // A real way back, rendered inside the app shell (the top bar is present).
    expect(screen.getByRole("link", { name: "Back to projects" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("serves the public system-status page without a session", async () => {
    window.history.pushState({}, "", "/status");
    vi.mocked(healthApi.liveness).mockResolvedValue({
      ok: true,
      status: 200,
      data: { status: "ok" },
    });
    vi.mocked(healthApi.readiness).mockResolvedValue({
      ok: true,
      status: 200,
      data: { status: "ok", checks: { database: "ok" } },
    });

    renderApp(); // anonymous (no token)

    expect(
      await screen.findByRole("heading", { name: "System status" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in to Polaris" })).toBeNull();
  });
});
