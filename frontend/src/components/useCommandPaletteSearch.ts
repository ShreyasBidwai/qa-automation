import { useEffect, useRef, useState } from "react";

import { searchApi } from "@/lib/api/client";
import type { SearchResultItem } from "@/lib/api/types";

const DEBOUNCE_MS = 200;

export interface CommandPaletteSearchState {
  results: SearchResultItem[];
  loading: boolean;
  error: string | null;
}

const EMPTY: CommandPaletteSearchState = { results: [], loading: false, error: null };

/**
 * Debounced, org-scoped name search for the command palette (ADR-0068). A blank
 * query clears immediately with no request. A request-id guard discards a stale
 * response — e.g. a slow "chec" landing after a faster "checkout" — so a late
 * response for an outdated keystroke can never clobber fresher results.
 */
export function useCommandPaletteSearch(query: string): CommandPaletteSearchState {
  const [state, setState] = useState<CommandPaletteSearchState>(EMPTY);
  const requestId = useRef(0);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      requestId.current += 1; // invalidate any in-flight request
      setState(EMPTY);
      return;
    }
    setState((prev) => ({ ...prev, loading: true, error: null }));
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      void searchApi.search(trimmed).then((result) => {
        if (requestId.current !== id) return; // superseded by a newer keystroke
        if (result.ok && result.data) {
          setState({ results: result.data.items, loading: false, error: null });
        } else {
          setState({
            results: [],
            loading: false,
            error: result.error ?? "Search failed.",
          });
        }
      });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  return state;
}
