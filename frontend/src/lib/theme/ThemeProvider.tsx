import { useCallback, useEffect, useState, type ReactNode } from "react";

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
 * Real light/dark theming (ADR-0073, greenfield): initialized from a persisted
 * choice, else the OS `prefers-color-scheme`; user-toggleable and persisted
 * thereafter. Applies by flipping `data-theme` on `<html>` — the CSS variables in
 * index.css do the rest (never `dark:` utilities sprinkled through components).
 * An inline script in index.html sets the SAME attribute (same storage key)
 * synchronously before React mounts, so there's no flash of the wrong theme on
 * load; this provider takes over from there for the toggle + persistence.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => storedTheme() ?? systemTheme());

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

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
