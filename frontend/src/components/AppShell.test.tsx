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
}));

import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken } from "@/lib/auth/session";

import { AppShell } from "./AppShell";

describe("AppShell", () => {
  beforeEach(() => clearToken());

  it("renders the primary nav, the account/support cluster, the wordmark, and content", () => {
    render(
      <AuthProvider>
        <AppShell>
          <div>page content</div>
        </AppShell>
      </AuthProvider>,
    );

    const primary = within(screen.getByRole("navigation", { name: "Primary" }));
    for (const label of ["Projects", "Findings", "Runs"]) {
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
    // The top bar carries the route-derived context + an account link.
    const topBar = within(screen.getByRole("banner"));
    expect(topBar.getByText("Projects")).toBeInTheDocument();
    expect(topBar.getByRole("link", { name: "Your account" })).toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
  });
});
