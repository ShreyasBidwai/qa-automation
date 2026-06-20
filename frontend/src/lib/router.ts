import { useSyncExternalStore } from "react";

/**
 * A tiny client-side router (no dependency) over the History API. `navigate`
 * pushes a path and notifies subscribers; `useLocation` re-renders on
 * back/forward and programmatic navigation. The dev server serves index.html
 * for all paths (SPA), so deep links work.
 */

const NAV_EVENT = "polaris:navigate";

export function navigate(to: string): void {
  if (to === window.location.pathname) return;
  window.history.pushState({}, "", to);
  window.dispatchEvent(new Event(NAV_EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(NAV_EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(NAV_EVENT, onChange);
  };
}

export function useLocation(): string {
  return useSyncExternalStore(
    subscribe,
    () => window.location.pathname,
    () => "/",
  );
}

/** True when `path` is the active route (exact, or a prefix for nested views). */
export function useIsActive(path: string): boolean {
  const location = useLocation();
  if (path === "/") return location === "/";
  return location === path || location.startsWith(`${path}/`);
}
