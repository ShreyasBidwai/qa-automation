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

import { authApi, projectApi } from "@/lib/api/client";
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

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
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
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
    expect(projectApi.list).toHaveBeenCalled();
  });
});
