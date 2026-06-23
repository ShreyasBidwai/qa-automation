import { useEffect, useState } from "react";

import { findingApi, runApi } from "@/lib/api/client";
import type { Finding } from "@/lib/api/types";

export interface SingleFindingState {
  finding: Finding | null;
  loading: boolean;
  error: string | null;
  /** Loaded fine, but the id isn't in the reachable set (honest, never invented). */
  notFound: boolean;
}

// The inbox is paginated server-side; without a run we scan one bounded page.
const INBOX_SCAN_LIMIT = 100;

/**
 * Load one finding by id for the dedicated full-screen view. There is no
 * GET /findings/{id} on trunk, so we read the authoritative source we can reach:
 * the run's findings when a run is known (`?run=` — covers any disposition,
 * open or muted), else the cross-project open inbox (best-effort, bounded). The
 * inbox/dashboard pass the run, so the common paths resolve exactly; a cold deep
 * link falls back to the open set. `notFound` is set honestly when the id isn't
 * in the reachable set.
 */
export function useFinding(id: string, runId: string | null): SingleFindingState {
  const [state, setState] = useState<SingleFindingState>({
    finding: null,
    loading: true,
    error: null,
    notFound: false,
  });

  useEffect(() => {
    let cancelled = false;
    setState({ finding: null, loading: true, error: null, notFound: false });

    async function load() {
      const result = runId
        ? await runApi.findings(runId)
        : await findingApi.listOpen({ limit: INBOX_SCAN_LIMIT, offset: 0 });
      if (cancelled) return;
      if (!result.ok || !result.data) {
        setState({
          finding: null,
          loading: false,
          error: result.error ?? "Couldn't load this finding.",
          notFound: false,
        });
        return;
      }
      const list = "findings" in result.data ? result.data.findings : result.data.items;
      const found = list.find((finding) => finding.id === id) ?? null;
      setState({
        finding: found,
        loading: false,
        error: null,
        notFound: found === null,
      });
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [id, runId]);

  return state;
}
