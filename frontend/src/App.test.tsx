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
  },
  jobApi: { get: vi.fn() },
  healthApi: { liveness: vi.fn(), readiness: vi.fn() },
}));

import { authApi, healthApi, projectApi } from "@/lib/api/client";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken, setToken } from "@/lib/auth/session";

import { App } from "./App";

function renderApp() {
  return render(
    <AuthProvider>
      <App />
    </AuthProvider>,
  );
}

describe("App auth gating", () => {
  beforeEach(() => {
    clearToken();
    vi.clearAllMocks();
    window.history.pushState({}, "", "/");
  });

  it("sends an unauthenticated visitor to sign in (no app data shown)", async () => {
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Sign in to Polaris" }),
    ).toBeInTheDocument();
    // The protected projects data is never requested while signed out.
    expect(projectApi.list).not.toHaveBeenCalled();
  });

  it("loads the app and its data once authenticated", async () => {
    setToken("tok-1");
    vi.mocked(authApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01" },
    });
    vi.mocked(projectApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [], total: 0, limit: 20, offset: 0 },
    });

    renderApp();

    // The real projects screen renders (not the sign-in front door).
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in to Polaris" })).toBeNull();
    expect(projectApi.list).toHaveBeenCalled();
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
