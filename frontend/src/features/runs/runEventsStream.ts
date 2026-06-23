import { API_BASE } from "@/lib/api/client";
import type { RunProgressEvent } from "@/lib/api/types";
import { getToken } from "@/lib/auth/session";

/**
 * Consume the live run-progress SSE stream (GET /runs/{id}/events/stream).
 *
 * Auth is a bearer token in the Authorization header, which `EventSource` can't
 * set — so we read the `text/event-stream` body with `fetch` + a ReadableStream
 * reader and parse the SSE frames ourselves. This also means NO automatic
 * reconnect: the promise resolves when the server closes the stream (it closes on
 * the terminal run event or once the run is over), and rejects on a transport
 * error — the caller decides what to do. Pass an `AbortSignal` to stop early
 * (terminal reached, or unmount).
 *
 * The backend frames look like:
 *   id: <seq>\nevent: progress\ndata: {json}\n\n
 * We only need the JSON on the `data:` line; frames are separated by a blank line.
 */
export async function streamRunEvents(
  runId: string,
  {
    signal,
    onEvents,
  }: { signal: AbortSignal; onEvents: (events: RunProgressEvent[]) => void },
): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_BASE}/runs/${runId}/events/stream`, {
    headers: {
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`run event stream failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Split on the SSE frame delimiter; keep the trailing partial frame buffered.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    const events: RunProgressEvent[] = [];
    for (const frame of frames) {
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      try {
        events.push(JSON.parse(dataLine.slice("data:".length).trim()));
      } catch {
        // A malformed frame is skipped rather than tearing down the whole stream.
      }
    }
    if (events.length > 0) onEvents(events);
  }
}
