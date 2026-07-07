import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY, ThemeProvider } from "./ThemeProvider";
import { useTheme } from "./useTheme";

function mockMatchMedia(prefersDark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" && prefersDark,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

function ThemeReadout() {
  const { theme, toggleTheme, setTheme } = useTheme();
  return (
    <div>
      <span>current: {theme}</span>
      <button type="button" onClick={toggleTheme}>
        toggle
      </button>
      <button type="button" onClick={() => setTheme("dark")}>
        force dark
      </button>
    </div>
  );
}

describe("ThemeProvider / useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });
  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
  });

  it("initializes from a persisted choice over the OS preference", () => {
    mockMatchMedia(true); // OS says dark
    localStorage.setItem(THEME_STORAGE_KEY, "light"); // but the user chose light
    render(
      <ThemeProvider>
        <ThemeReadout />
      </ThemeProvider>,
    );
    expect(screen.getByText("current: light")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("falls back to the OS preference when nothing is persisted", () => {
    mockMatchMedia(true);
    render(
      <ThemeProvider>
        <ThemeReadout />
      </ThemeProvider>,
    );
    expect(screen.getByText("current: dark")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("defaults to light when the OS has no preference", () => {
    mockMatchMedia(false);
    render(
      <ThemeProvider>
        <ThemeReadout />
      </ThemeProvider>,
    );
    expect(screen.getByText("current: light")).toBeInTheDocument();
  });

  it("toggles the theme, applies data-theme, and persists the choice", () => {
    mockMatchMedia(false);
    render(
      <ThemeProvider>
        <ThemeReadout />
      </ThemeProvider>,
    );

    fireEvent.click(screen.getByText("toggle"));
    expect(screen.getByText("current: dark")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    fireEvent.click(screen.getByText("toggle"));
    expect(screen.getByText("current: light")).toBeInTheDocument();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("setTheme sets an explicit theme regardless of the current one", () => {
    mockMatchMedia(false);
    render(
      <ThemeProvider>
        <ThemeReadout />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByText("force dark"));
    expect(screen.getByText("current: dark")).toBeInTheDocument();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});
