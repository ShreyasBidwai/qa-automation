import { useEffect, useRef, useState } from "react";

import { API_BASE } from "@/lib/api/client";
import { getToken } from "@/lib/auth/session";

/**
 * Load one run step's screenshot as an object URL (the live "browser frame").
 *
 * The bytes are served only through the AUTHORIZED endpoint
 * `GET /runs/{id}/events/screenshot?seq=N`, which needs the bearer token — an
 * `<img src>` can't send headers, so we `fetch` the blob with the token and hand
 * back a `URL.createObjectURL` reference, revoked on cleanup.
 *
 * Smooth advance: when `seq` changes (the crawl moved to the next page) we keep the
 * PREVIOUS frame on screen and only swap once the next one has loaded — so the live
 * view reads like a screen, not a slideshow that blinks to a spinner between frames.
 * The spinner shows only for the very first load; a transient fetch error keeps the
 * last good frame rather than blanking it.
 */
type ShotState = "loading" | "ready" | "error";

export function useRunScreenshot(
  runId: string,
  seq: number,
  enabled: boolean,
): { url: string | null; state: ShotState } {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<ShotState>("loading");
  // The currently-displayed object URL, tracked so we revoke it only AFTER the next
  // frame has replaced it (and on unmount) — never while the <img> still shows it.
  const currentUrl = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const controller = new AbortController();

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
        const next = URL.createObjectURL(blob);
        const previous = currentUrl.current;
        currentUrl.current = next;
        setUrl(next);
        setState("ready");
        // The <img> now points at `next`; the old frame is no longer referenced.
        if (previous) URL.revokeObjectURL(previous);
      } catch {
        if (cancelled) return;
        // Keep the last good frame on a transient error; only surface "error" when
        // there's nothing to show yet (the first frame failed).
        setState(currentUrl.current ? "ready" : "error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId, seq, enabled]);

  // Revoke the final frame when the component goes away.
  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );

  return { url, state };
}
