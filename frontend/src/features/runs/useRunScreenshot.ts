import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api/client";
import { getToken } from "@/lib/auth/session";

/**
 * Load one run step's screenshot as an object URL (the live "browser frame").
 *
 * The bytes are served only through the AUTHORIZED endpoint
 * `GET /runs/{id}/events/screenshot?seq=N`, which needs the bearer token — an
 * `<img src>` can't send headers, so we `fetch` the blob with the token and hand
 * back a `URL.createObjectURL` reference, revoked on cleanup. Refetches when `seq`
 * changes (so the top frame animates as the crawl advances) and only while
 * `enabled` (a collapsed per-step panel does no work).
 */
type ShotState = "loading" | "ready" | "error";

export function useRunScreenshot(
  runId: string,
  seq: number,
  enabled: boolean,
): { url: string | null; state: ShotState } {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<ShotState>("loading");

  useEffect(() => {
    if (!enabled) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    const controller = new AbortController();
    setState("loading");

    void (async () => {
      try {
        const token = getToken();
        const response = await fetch(
          `${API_BASE}/runs/${runId}/events/screenshot?seq=${seq}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error(String(response.status));
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [runId, seq, enabled]);

  return { url, state };
}
