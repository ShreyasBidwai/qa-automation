import { useCallback, useEffect, useState } from "react";

import type { ApiResult } from "@/lib/api/client";

/** A single-shot admin fetch (queue stats, a job list, a detail record) with a manual
 *  reload. `fetcher` must be memoized by the caller — its identity changing (a new id,
 *  a new filter) refetches. Failures surface as `error`, never a crash. */
export interface AdminResource<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAdminResource<T>(
  fetcher: () => Promise<ApiResult<T>>,
  enabled = true,
): AdminResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void fetcher().then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setData(result.data);
        setError(null);
      } else {
        setData(null);
        setError(result.error ?? "Couldn't load this.");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [fetcher, enabled, nonce]);

  const reload = useCallback(() => setNonce((current) => current + 1), []);
  return { data, loading, error, reload };
}

/** Debounce a fast-changing value (a search box) so a keystroke doesn't fire a request
 *  per character — the list refetches once the typing settles. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
