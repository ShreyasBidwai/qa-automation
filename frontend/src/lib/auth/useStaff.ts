import { useSyncExternalStore } from "react";

import { adminApi } from "@/lib/api/client";
import type { AdminMe, StaffPermission } from "@/lib/api/types";

import { getToken, subscribeToken } from "./session";

/**
 * The caller's operator-console identity, loaded ONCE per session from GET /admin/me.
 *
 * `staff === null` means "not staff" — the endpoint 403s for a non-staff caller, and
 * we treat that (and any load failure) as "no access" rather than a crash. The result
 * is cached at module level and shared across every component (via a tiny external
 * store), so navigating between admin pages never refetches it. A sign-in/out clears
 * the cache so the next question re-resolves against the new session.
 *
 * The server is the real authority — it 403s regardless. `hasPerm` only lets the UI
 * hide actions it already knows will be refused.
 */
export interface StaffAccess {
  loading: boolean;
  staff: AdminMe | null;
  hasPerm: (permission: StaffPermission) => boolean;
}

interface StaffSnapshot {
  loading: boolean;
  staff: AdminMe | null;
}

let snapshot: StaffSnapshot = { loading: true, staff: null };
let inFlight = false;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function setSnapshot(next: StaffSnapshot): void {
  snapshot = next;
  emit();
}

/** Resolve the staff identity once. Signed-out or a 403/error ⇒ not staff (no crash). */
function ensureLoaded(): void {
  // Already loaded (or loading) — the cache stands until the token changes.
  if (inFlight || !snapshot.loading) return;
  if (!getToken()) {
    setSnapshot({ loading: false, staff: null });
    return;
  }
  inFlight = true;
  void adminApi.me().then((result) => {
    inFlight = false;
    setSnapshot({ loading: false, staff: result.ok ? result.data : null });
  });
}

// A sign-in/out changes who's asking — drop the cached identity and reload lazily
// (the next subscribing component triggers the refetch).
subscribeToken(() => {
  inFlight = false;
  setSnapshot({ loading: true, staff: null });
});

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Kick the (idempotent) load when the first consumer mounts.
  ensureLoaded();
  return () => {
    listeners.delete(listener);
  };
}

/** Test-only: forget the cached staff identity so each test starts from a clean load. */
export function resetStaffCache(): void {
  inFlight = false;
  snapshot = { loading: true, staff: null };
}

export function useStaff(): StaffAccess {
  const snap = useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => snapshot,
  );
  return {
    loading: snap.loading,
    staff: snap.staff,
    hasPerm: (permission) => snap.staff?.permissions.includes(permission) ?? false,
  };
}
