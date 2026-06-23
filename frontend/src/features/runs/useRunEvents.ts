import { useCallback, useEffect, useState } from "react";

import { runApi } from "@/lib/api/client";
import type { RunProgressEvent } from "@/lib/api/types";

import { isTerminalEvent } from "./runEvents";
import { streamRunEvents } from "./runEventsStream";

export type RunEventsConnection = "connecting" | "live" | "done" | "error";

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
 *  3. CLOSE — the fetch-stream resolves when the server closes (terminal, or the
 *     run otherwise ended) → `done`; a transport error reconciles with one more
 *     replay and surfaces `error` (with `reconnect()` to resume) only if the run
 *     isn't actually finished. There is no auto-reconnect loop.
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
        // 3a) Server closed the stream cleanly → the run is over.
        if (cancelled) return;
        setTerminal(sawTerminal);
        setConnection("done");
      } catch {
        if (cancelled) return;
        if (sawTerminal || controller.signal.aborted) {
          setTerminal(sawTerminal);
          setConnection("done");
          return;
        }
        // 3b) Transport error mid-run — reconcile once, then surface honestly.
        const lastSeq =
          ordered.length > 0 ? ordered[ordered.length - 1].seq : undefined;
        const reconcile = await runApi.events(runId, lastSeq);
        if (cancelled) return;
        if (reconcile.ok && reconcile.data) ingest(reconcile.data.events);
        setTerminal(sawTerminal);
        setConnection(sawTerminal ? "done" : "error");
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId, attempt]);

  return { events, connection, terminal, reconnect };
}
