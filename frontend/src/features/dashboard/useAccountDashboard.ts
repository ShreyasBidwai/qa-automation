import { useEffect, useState } from "react";

import { accountApi } from "@/lib/api/client";
import type { AccountDashboard } from "@/lib/api/types";

export interface AccountDashboardState {
  data: AccountDashboard | null;
  loading: boolean;
  error: string | null;
}

/** Load the account-wide dashboard for a time window; re-fetches when the range changes.
 *  Defensive — a failure surfaces as an error string, never a crash (ADR-0065). */
export function useAccountDashboard(rangeDays: number): AccountDashboardState {
  const [state, setState] = useState<AccountDashboardState>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    void accountApi.dashboard(rangeDays).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setState({ data: result.data, loading: false, error: null });
      } else {
        setState({
          data: null,
          loading: false,
          error: result.error ?? "Couldn't load your dashboard.",
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [rangeDays]);

  return state;
}
