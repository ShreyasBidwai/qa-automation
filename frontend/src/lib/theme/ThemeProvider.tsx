import { useCallback, useState, type ReactNode } from "react";

import { ThemeContext, type Theme } from "./useTheme";

export const THEME_STORAGE_KEY = "polaris:theme";

function systemTheme(): Theme {
  // jsdom (unit tests) doesn't implement matchMedia unless a test stubs it —
  // default to light rather than throwing.
  if (typeof window.matchMedia !== "function") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The persisted theme, if the user has explicitly chosen one, else null. */
function storedTheme(): Theme | null {
  const value = localStorage.getItem(THEME_STORAGE_KEY);
  return value === "light" || value === "dark" ? value : null;
}

/**
 * Real light/dark theming (ADR-0073, greenfield): holds the user's theme
 * *preference* — initialized from a persisted choice, else the OS
 * `prefers-color-scheme` — and is user-toggleable + persisted thereafter.
 *
 * It deliberately does NOT write `data-theme` to `<html>` itself. Dark mode is a
 * signed-in surface: the authenticated app shell (`AppShell`) applies this
 * preference to `<html>` while it is mounted, and reverts to light on sign-out —
 * so the public front door (login / sign-up / landing), which is never wrapped in
 * the shell, always stays on the light brand. The inline script in index.html
 * mirrors the same rule for first paint (only a signed-in session gets a dark
 * pre-render; everyone else paints light).
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => storedTheme() ?? systemTheme());

  const setTheme = useCallback((next: Theme) => {
    localStorage.setItem(THEME_STORAGE_KEY, next);
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
