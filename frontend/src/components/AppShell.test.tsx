import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("renders the primary nav, the account/support cluster, the wordmark, and content", () => {
    render(
      <AppShell>
        <div>page content</div>
      </AppShell>,
    );

    const primary = within(screen.getByRole("navigation", { name: "Primary" }));
    for (const label of ["Findings", "Projects", "Runs"]) {
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
    expect(screen.getByText("page content")).toBeInTheDocument();
  });
});
