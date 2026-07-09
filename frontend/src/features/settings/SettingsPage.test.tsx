import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ToastProvider } from "@/components/ToastProvider";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";

import { SettingsPage } from "./SettingsPage";

function renderSettings() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders the Appearance and Notifications sections", () => {
    renderSettings();
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("Appearance")).toBeInTheDocument();
    expect(screen.getByText("Notifications")).toBeInTheDocument();
  });

  it("reflects the current theme and switches it on click", () => {
    renderSettings();
    const light = screen.getByRole("radio", { name: "light" });
    const dark = screen.getByRole("radio", { name: "dark" });
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveAttribute("aria-checked", "false");

    fireEvent.click(dark);

    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(light).toHaveAttribute("aria-checked", "false");
    // The choice is recorded + persisted here; applying it to <html> is the signed-in
    // app shell's job (AppShell), so that the public front door stays on the light brand.
    expect(localStorage.getItem("polaris:theme")).toBe("dark");
  });

  it("defaults notifications to on, and toggles + persists off", () => {
    renderSettings();
    const toggle = screen.getByRole("switch", { name: "Show toast notifications" });
    expect(toggle).toHaveAttribute("aria-checked", "true");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(localStorage.getItem("polaris:notifications-enabled")).toBe("false");
  });

  it("initializes the notifications switch from a persisted 'off' choice", () => {
    localStorage.setItem("polaris:notifications-enabled", "false");
    renderSettings();
    expect(
      screen.getByRole("switch", { name: "Show toast notifications" }),
    ).toHaveAttribute("aria-checked", "false");
  });
});
