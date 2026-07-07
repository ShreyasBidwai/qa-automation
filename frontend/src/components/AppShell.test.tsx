import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  authApi: {
    me: vi.fn(),
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    updateProfile: vi.fn(),
  },
  searchApi: { search: vi.fn() },
}));

import { searchApi } from "@/lib/api/client";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken } from "@/lib/auth/session";

import { AppShell } from "./AppShell";

describe("AppShell", () => {
  beforeEach(() => {
    clearToken();
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

  describe("command palette (ADR-0068)", () => {
    beforeEach(() => {
      vi.mocked(searchApi.search).mockReset();
    });

    it("opens on clicking the search button", () => {
      render(
        <AuthProvider>
          <AppShell>
            <div>content</div>
          </AppShell>
        </AuthProvider>,
      );
      expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();

      fireEvent.click(screen.getByText("Search findings…"));
      expect(
        screen.getByRole("dialog", { name: "Command palette" }),
      ).toBeInTheDocument();
    });

    it("opens on Ctrl+K from anywhere in the shell", () => {
      render(
        <AuthProvider>
          <AppShell>
            <div>content</div>
          </AppShell>
        </AuthProvider>,
      );
      fireEvent.keyDown(window, { key: "k", ctrlKey: true });
      expect(
        screen.getByRole("dialog", { name: "Command palette" }),
      ).toBeInTheDocument();
    });
  });

  describe("mobile navigation drawer", () => {
    it("is closed by default and opens on the hamburger button", () => {
      render(
        <AuthProvider>
          <AppShell>
            <div>content</div>
          </AppShell>
        </AuthProvider>,
      );
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
      render(
        <AuthProvider>
          <AppShell>
            <div>content</div>
          </AppShell>
        </AuthProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
    });

    it("closes on Escape", () => {
      render(
        <AuthProvider>
          <AppShell>
            <div>content</div>
          </AppShell>
        </AuthProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      fireEvent.keyDown(screen.getByRole("dialog", { name: "Navigation" }), {
        key: "Escape",
      });
      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
    });

    it("closes automatically when a nav link is followed (route change)", () => {
      render(
        <AuthProvider>
          <AppShell>
            <div>content</div>
          </AppShell>
        </AuthProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
      const drawer = screen.getByRole("dialog", { name: "Navigation" });
      fireEvent.click(within(drawer).getByRole("link", { name: "Projects" }));

      expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull();
      expect(window.location.pathname).toBe("/projects");
    });
  });
});
