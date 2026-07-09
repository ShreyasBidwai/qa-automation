import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
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
  searchApi: { search: vi.fn() },
  runApi: { active: vi.fn(), get: vi.fn() },
}));

import { adminApi, authApi, runApi, searchApi } from "@/lib/api/client";
import type { AdminMe } from "@/lib/api/types";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken, setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";
import { ToastProvider } from "@/components/ToastProvider";

import { AppShell } from "./AppShell";

function staff(permissions: string[]): AdminMe {
  return {
    user_id: "s1",
    email: "ops@polaris.dev",
    staff_role: "superadmin",
    permissions,
  };
}

function renderShell(content: ReactNode) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <AppShell>{content}</AppShell>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    clearToken();
    resetStaffCache();
    vi.mocked(adminApi.me).mockReset();
    window.history.pushState({}, "", "/");
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    // useRunLifecycleToasts polls this on mount — default to "nothing running" so
    // tests that don't care about it never see an unmocked-call crash.
    vi.mocked(runApi.active).mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: null, project_id: null, mode: null, status: null },
    });
  });

  it("renders the primary nav, the account/support cluster, the wordmark, and content", () => {
    renderShell(<div>page content</div>);

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
    renderShell(<div>content</div>);
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
    renderShell(<div>content</div>);
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
    renderShell(<div>content</div>);
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
    renderShell(<div>content</div>);
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

    renderShell(<div>content</div>);

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

  describe("command palette (ADR-0072)", () => {
    beforeEach(() => {
      vi.mocked(searchApi.search).mockReset();
    });

    it("opens on clicking the search button", () => {
      renderShell(<div>content</div>);
      expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();

      fireEvent.click(screen.getByText("Search findings…"));
      expect(
        screen.getByRole("dialog", { name: "Command palette" }),
      ).toBeInTheDocument();
    });

    it("opens on Ctrl+K from anywhere in the shell", () => {
      renderShell(<div>content</div>);
      fireEvent.keyDown(window, { key: "k", ctrlKey: true });
      expect(
        screen.getByRole("dialog", { name: "Command palette" }),
      ).toBeInTheDocument();
    });
  });

  describe("mobile navigation drawer", () => {
    it("is closed by default and opens on the hamburger button", () => {
      renderShell(<div>content</div>);
      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      const drawer = screen.getByRole("dialog", { name: "Navigation" });
      expect(drawer).toBeInTheDocument();

      // The exact same nav entries as the desktop sidebar, inside the drawer.
      const drawerNav = within(drawer).getByRole("navigation", { name: "Primary" });
      for (const label of ["Dashboard", "Projects", "Findings", "Runs"]) {
        expect(
          within(drawerNav).getByRole("link", { name: label }),
        ).toBeInTheDocument();
      }
    });

    it("closes on the drawer's own close button", () => {
      renderShell(<div>content</div>);
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
    });

    it("closes on Escape", () => {
      renderShell(<div>content</div>);
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      fireEvent.keyDown(screen.getByRole("dialog", { name: "Navigation" }), {
        key: "Escape",
      });
      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
    });

    it("closes automatically when a nav link is followed (route change)", () => {
      renderShell(<div>content</div>);
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      const drawer = screen.getByRole("dialog", { name: "Navigation" });
      fireEvent.click(within(drawer).getByRole("link", { name: "Projects" }));

      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
      expect(window.location.pathname).toBe("/projects");
    });
  });

  describe("theme toggle (ADR-0073)", () => {
    it("defaults to light and switches the whole document to dark on click", () => {
      renderShell(<div>content</div>);
      expect(document.documentElement.getAttribute("data-theme")).toBe("light");

      fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
      expect(
        screen.getByRole("button", { name: "Switch to light theme" }),
      ).toBeInTheDocument();
    });
  });
});
