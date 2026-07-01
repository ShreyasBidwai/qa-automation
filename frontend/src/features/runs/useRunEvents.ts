import { useCallback, useEffect, useState } from "react";

import { runApi } from "@/lib/api/client";
import type { RunProgressEvent } from "@/lib/api/types";

import { isTerminalEvent } from "./runEvents";
import { streamRunEvents } from "./runEventsStream";
import { isTerminal } from "./runStatus";

export type RunEventsConnection = "connecting" | "live" | "done" | "error";

// The backend SSE stream self-closes at a server safety cap (~5 min) even while a
// run is still going. When it closes with no terminal event, we re-open it after
// this short beat so a long run keeps streaming live instead of stranding the
// viewer on a false "Run ended".
const RECONNECT_DELAY_MS = 1200;

export interface RunEventsState {
  events: RunProgressEvent[];
  connection: RunEventsConnection;
  /** True once a run-level terminal event was seen (the journey really finished). */
  terminal: boolean;
  /** Re-open the stream (after a transport error, or to resume a long run). */
  reconnect: () => void;
}

/**
 * Drive the live run view from the backend's progress events (ADR-0050):
 *
 *  1. CATCH-UP — replay GET /runs/{id}/events once on connect, so a late joiner
 *     (or a finished run) immediately sees the whole journey. If that replay
 *     already contains the terminal event, the run is over — render it, no stream.
 *  2. LIVE — otherwise open the SSE stream and append events as they arrive, in
 *     seq order, de-duplicated against the catch-up (the stream re-sends from the
 *     start). On the terminal event we abort and settle to `done`.
 *  3. CLOSE — the fetch-stream resolves when the server closes it. If a terminal
 *     event was seen the run is over → `done`. Otherwise the close is ambiguous
 *     (the ~5-min safety cap vs. a genuinely drained run), so we ask the
 *     authoritative job status: still running → re-open the stream (a long run must
 *     never read as "ended"); terminal → `done`; unreachable → `error` (with
 *     `reconnect()` to resume).
 */
export function useRunEvents(runId: string): RunEventsState {
  const [events, setEvents] = useState<RunProgressEvent[]>([]);
  const [connection, setConnection] = useState<RunEventsConnection>("connecting");
  const [terminal, setTerminal] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const reconnect = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    const seen = new Set<number>();
    let ordered: RunProgressEvent[] = [];
    let sawTerminal = false;

    function ingest(incoming: RunProgressEvent[]): void {
      let changed = false;
      for (const event of incoming) {
        if (seen.has(event.seq)) continue;
        seen.add(event.seq);
        ordered.push(event);
        changed = true;
        if (isTerminalEvent(event)) sawTerminal = true;
      }
      if (!changed || cancelled) return;
      ordered = [...ordered].sort((a, b) => a.seq - b.seq);
      setEvents(ordered);
    }

    // The stream closed with no terminal event — ambiguous (safety cap vs. a
    // drained run). Ask the authoritative job status: still running → re-open the
    // stream so the live view continues; terminal → settle `done`; unreachable →
    // `error` (a manual Reconnect), never a silent hot loop.
    async function settleOrReconnect(): Promise<void> {
      const status = await runApi.get(runId);
      if (cancelled) return;
      const jobStatus = status.ok && status.data ? status.data.status : null;
      if (jobStatus !== null && !isTerminal(jobStatus)) {
        setConnection("connecting"); // keep the banner "live", not "ended"
        reconnectTimer = setTimeout(() => {
          if (!cancelled) setAttempt((value) => value + 1);
        }, RECONNECT_DELAY_MS);
        return;
      }
      setTerminal(sawTerminal);
      setConnection(jobStatus === null ? "error" : "done");
    }

    async function load() {
      setConnection("connecting");

      // 1) Catch-up replay (also the whole story for a finished run).
      const replay = await runApi.events(runId);
      if (cancelled) return;
      if (replay.ok && replay.data) ingest(replay.data.events);
      if (sawTerminal) {
        setTerminal(true);
        setConnection("done");
        return;
      }

      // 2) Live stream for the rest.
      setConnection("live");
      try {
        await streamRunEvents(runId, {
          signal: controller.signal,
          onEvents: (incoming) => {
            ingest(incoming);
            if (sawTerminal) controller.abort(); // terminal → stop reading
          },
        });
        // 3a) Server closed the stream cleanly.
        if (cancelled) return;
        if (sawTerminal) {
          setTerminal(true);
          setConnection("done");
          return;
        }
        await settleOrReconnect();
      } catch {
        if (cancelled) return;
        if (sawTerminal || controller.signal.aborted) {
          setTerminal(sawTerminal);
          setConnection("done");
          return;
        }
        // 3b) Transport error mid-run — reconcile once, then settle-or-reconnect.
        const lastSeq =
          ordered.length > 0 ? ordered[ordered.length - 1].seq : undefined;
        const reconcile = await runApi.events(runId, lastSeq);
        if (cancelled) return;
        if (reconcile.ok && reconcile.data) ingest(reconcile.data.events);
        if (sawTerminal) {
          setTerminal(true);
          setConnection("done");
          return;
        }
        await settleOrReconnect();
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [runId, attempt]);

  return { events, connection, terminal, reconnect };
}
