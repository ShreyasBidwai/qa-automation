import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  authApi: {
    me: vi.fn(),
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    updateProfile: vi.fn(),
  },
  // The shell asks /admin/me (via useStaff) to decide whether to show the Admin group.
  adminApi: { me: vi.fn() },
}));

import { adminApi, authApi } from "@/lib/api/client";
import type { AdminMe } from "@/lib/api/types";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken, setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";

import { AppShell } from "./AppShell";

function staff(permissions: string[]): AdminMe {
  return {
    user_id: "s1",
    email: "ops@polaris.dev",
    staff_role: "superadmin",
    permissions,
  };
}

describe("AppShell", () => {
  beforeEach(() => {
    clearToken();
    resetStaffCache();
    vi.mocked(adminApi.me).mockReset();
    window.history.pushState({}, "", "/");
  });

  it("renders the primary nav, the account/support cluster, the wordmark, and content", () => {
    render(
      <AuthProvider>
        <AppShell>
          <div>page content</div>
        </AppShell>
      </AuthProvider>,
    );

    const primary = within(screen.getByRole("navigation", { name: "Primary" }));
    for (const label of ["Dashboard", "Projects", "Findings", "Runs"]) {
      expect(primary.getByRole("link", { name: label })).toBeInTheDocument();
    }

    const support = within(
      screen.getByRole("navigation", { name: "Account and support" }),
    );
    for (const label of ["Account", "Settings", "Help"]) {
      expect(support.getByRole("link", { name: label })).toBeInTheDocument();
    }

    // The wordmark links home (sidebar + mobile top bar).
    expect(screen.getAllByLabelText("Polaris — home").length).toBeGreaterThanOrEqual(1);
    // The top bar carries the route-derived context + an account link. The root path
    // is the account Dashboard (ADR-0065).
    const topBar = within(screen.getByRole("banner"));
    expect(topBar.getByText("Dashboard")).toBeInTheDocument();
    expect(topBar.getByRole("link", { name: "Your account" })).toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
  });

  it("exposes Gitea + PM-tool connector tabs in their own nav group", () => {
    window.history.pushState({}, "", "/connectors/gitea");
    render(
      <AuthProvider>
        <AppShell>
          <div>content</div>
        </AppShell>
      </AuthProvider>,
    );
    const connectors = within(screen.getByRole("navigation", { name: "Connectors" }));
    expect(connectors.getByRole("link", { name: "Gitea" })).toHaveAttribute(
      "href",
      "/connectors/gitea",
    );
    expect(connectors.getByRole("link", { name: "PM tool" })).toHaveAttribute(
      "href",
      "/connectors/pm",
    );
    // The open connector's tab is marked current; its sibling is not.
    expect(connectors.getByRole("link", { name: "Gitea" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(connectors.getByRole("link", { name: "PM tool" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("highlights only the deepest matching nav entry", () => {
    window.history.pushState({}, "", "/runs/ongoing");
    render(
      <AuthProvider>
        <AppShell>
          <div>content</div>
        </AppShell>
      </AuthProvider>,
    );
    const primary = within(screen.getByRole("navigation", { name: "Primary" }));
    // On /runs/ongoing the longest prefix wins: "Ongoing run" is current, "Runs" not.
    expect(primary.getByRole("link", { name: "Ongoing run" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(primary.getByRole("link", { name: "Runs" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps 'Runs' highlighted for a specific run's pages", () => {
    window.history.pushState({}, "", "/runs/abc123/live");
    render(
      <AuthProvider>
        <AppShell>
          <div>content</div>
        </AppShell>
      </AuthProvider>,
    );
    const primary = within(screen.getByRole("navigation", { name: "Primary" }));
    expect(primary.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(primary.getByRole("link", { name: "Ongoing run" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("hides the Admin nav group from a non-staff caller", () => {
    // No token → /admin/me is never asked; the caller is treated as not staff.
    render(
      <AuthProvider>
        <AppShell>
          <div>content</div>
        </AppShell>
      </AuthProvider>,
    );
    expect(screen.queryByRole("navigation", { name: "Admin" })).toBeNull();
    expect(adminApi.me).not.toHaveBeenCalled();
  });

  it("shows the Admin nav group to a staff caller, gated per permission", async () => {
    setToken("staff-token");
    // A signed-in session (the shell mounts inside AuthProvider, which validates it).
    vi.mocked(authApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        id: "s1",
        email: "ops@polaris.dev",
        name: null,
        created_at: "2026-01-01",
      },
    });
    // A staffer who can see ops + tenants but NOT users/audit: only those tabs appear.
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: staff(["view_ops", "view_tenants"]),
    });

    render(
      <AuthProvider>
        <AppShell>
          <div>content</div>
        </AppShell>
      </AuthProvider>,
    );

    const admin = within(
      await screen.findByRole("navigation", { name: "Operator console" }),
    );
    expect(admin.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(admin.getByRole("link", { name: "Tenants" })).toBeInTheDocument();
    expect(admin.getByRole("link", { name: "Queue" })).toBeInTheDocument();
    expect(admin.getByRole("link", { name: "Incidents" })).toBeInTheDocument();
    // The flywheel dashboard rides view_ops, so it appears for this caller too.
    expect(admin.getByRole("link", { name: "Flywheel" })).toBeInTheDocument();
    // Permissions the caller lacks hide their tabs entirely.
    expect(admin.queryByRole("link", { name: "Users" })).toBeNull();
    expect(admin.queryByRole("link", { name: "Audit" })).toBeNull();
    // Staff are operators, not customers — the create/test workflow nav is gone.
    expect(screen.queryByRole("link", { name: "Projects" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Runs" })).toBeNull();
  });
});
