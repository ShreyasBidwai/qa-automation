import { useEffect, useState } from "react";

import type { ApiResult } from "./api/client";

/** The paged-list envelope every list endpoint returns. */
export interface Paged<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PagedList<T> {
  items: T[];
  total: number;
  offset: number;
  pageSize: number;
  loading: boolean;
  error: string | null;
  hasPrev: boolean;
  hasNext: boolean;
  next: () => void;
  prev: () => void;
}

/**
 * Fetch one bounded page of a list endpoint, with prev/next paging. `fetchPage`
 * should be memoized by the caller (its identity changing — e.g. a different
 * project — refetches); `resetKey` returns paging to the first page when it
 * changes. Failures surface as `error`, never a crash.
 */
export function usePagedList<T>(
  fetchPage: (offset: number) => Promise<ApiResult<Paged<T>>>,
  options: { pageSize: number; enabled?: boolean; resetKey?: string },
): PagedList<T> {
  const { pageSize, enabled = true, resetKey = "" } = options;
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Paged<T> | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  // Return to the first page whenever the reset key changes (e.g. a switch).
  useEffect(() => {
    setOffset(0);
  }, [resetKey]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void fetchPage(offset).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setData(result.data);
        setError(null);
      } else {
        setData(null);
        setError(result.error ?? "Could not load the list.");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [fetchPage, offset, enabled]);

  const total = data?.total ?? 0;
  // "Enabled but not yet settled" counts as loading, so a list never flashes its
  // empty state before its first fetch resolves (which would detach the node a
  // findBy* just matched).
  const settled = data !== null || error !== null;
  return {
    items: data?.items ?? [],
    total,
    offset,
    pageSize,
    loading: enabled && (loading || !settled),
    error,
    hasPrev: offset > 0,
    hasNext: offset + pageSize < total,
    next: () => setOffset((current) => current + pageSize),
    prev: () => setOffset((current) => Math.max(0, current - pageSize)),
  };
}
