import { useEffect, useRef } from "react";

import { useToast } from "@/components/useToast";
import { runApi } from "@/lib/api/client";
import { navigate } from "@/lib/router";

import { isTerminal } from "./runStatus";

const POLL_MS = 4000;

/**
 * App-wide "a run finished" toast (mission item 3): mounted once at the app shell
 * so a run started from one page still announces its outcome even after the
 * operator has navigated elsewhere — e.g. back to the dashboard, or off to start a
 * different run.
 *
 * Piggybacks on the SAME REST endpoints `useActiveRun` already polls
 * (`GET /runs/active`, `GET /runs/{id}`) — no new backend push channel — but can't
 * reuse that hook verbatim: `useActiveRun` deliberately PINS to the first run it
 * finds and stops polling forever, which is right for the "Ongoing run" page (it
 * remounts fresh each visit) but wrong for a session-long watcher, which instead
 * needs to notice `/runs/active` go back to empty (the run finished) and re-arm for
 * the next one.
 */
export function useRunLifecycleToasts(): void {
  const { notify } = useToast();
  const trackedRunId = useRef<string | null>(null);
  const notifiedRunIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function announceCompletion(runId: string): Promise<void> {
      const result = await runApi.get(runId);
      if (cancelled || !result.ok || !result.data) return;
      const { status } = result.data;
      if (!isTerminal(status) || notifiedRunIds.current.has(runId)) return;
      notifiedRunIds.current.add(runId);
      const succeeded = status === "succeeded";
      notify({
        title: succeeded ? "Run completed" : "Run failed",
        tone: succeeded ? "success" : "error",
        action: { label: "View", onClick: () => navigate(`/runs/${runId}/findings`) },
      });
    }

    async function poll(): Promise<void> {
      const result = await runApi.active();
      if (!cancelled && result.ok && result.data) {
        const activeId = result.data.run_id;
        if (activeId) {
          trackedRunId.current = activeId;
        } else if (trackedRunId.current) {
          // The run that was active is no longer — it just finished; look up its
          // final status once, exactly like the "Ongoing run" page would.
          const finished = trackedRunId.current;
          trackedRunId.current = null;
          void announceCompletion(finished);
        }
      }
      if (!cancelled) timer = setTimeout(() => void poll(), POLL_MS);
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [notify]);
}
