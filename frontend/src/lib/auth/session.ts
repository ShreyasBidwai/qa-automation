/**
 * The persisted auth session — just the B2 bearer token. Kept in localStorage so
 * a reload stays signed in, with a tiny subscribe channel so the auth context can
 * react when the token is set (sign-in) or cleared (sign-out, or a 401 from the
 * API client). The token is the only secret here; nothing else is stored.
 */

const STORAGE_KEY = "polaris.auth.token";

let token: string | null = null;
let loaded = false;
const listeners = new Set<() => void>();

function load(): string | null {
  if (loaded) return token;
  loaded = true;
  try {
    token = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    token = null; // private mode / storage disabled — degrade to in-memory.
  }
  return token;
}

export function getToken(): string | null {
  return load();
}

export function setToken(value: string): void {
  token = value;
  loaded = true;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // ignore — keep it in memory for this session.
  }
  emit();
}

export function clearToken(): void {
  token = null;
  loaded = true;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore.
  }
  emit();
}

/** Subscribe to token changes (set/clear). Returns an unsubscribe fn. */
export function subscribeToken(callback: () => void): () => void {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

function emit(): void {
  for (const listener of listeners) listener();
}
