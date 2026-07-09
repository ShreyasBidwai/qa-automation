# ADR-0067 — Reap orphaned jobs, so a dead run never shows as "ongoing"

## Status

Accepted.

## Context

The "Ongoing run" view showed a run frozen at "67 steps / 6m58s" when nothing was
running. The DB told the story: **six `jobs` rows stuck `status='running'` for up to 12
days**, several with their `runs` row already `interrupted`. The job's lease
(`locked_at`) was never released.

Two gaps caused it:

1. **Startup reconciled runs but not jobs.** The worker's startup sweep flips orphaned
   `runs` (`running` → `interrupted`) but left the backing `jobs` rows `running`. Since
   the "Ongoing run" query filters on **job** status (`queued`/`running`), those orphans
   kept surfacing.
2. **Nothing reaped a leaked lease.** `stuck_jobs()` (running jobs whose lease exceeds a
   threshold) existed but was only *reported* by an ops endpoint — never acted on. A job
   whose worker died (or a sibling worker in a multi-worker deploy) leaked its lease
   forever. The per-job watchdog (`asyncio.wait_for`, ADR-0034) bounds a *handler* that
   hangs, but it can't fire for a *process that died* — the coroutine is gone with it.

## Decision

**The queue reaps orphaned/wedged running jobs; the "Ongoing run" query trusts only a
fresh lease.**

- `JobQueue.reclaim_stale_running(older_than_seconds)` — `FOR UPDATE SKIP LOCKED` over
  `running` jobs whose lease is older than the threshold, transitioning each to
  **`failed`** (terminal, lease released) and returning the `(id, kind)` pairs. Terminal,
  never a silent re-queue: re-running a crashed job behind the operator's back is
  surprising, and a wedged run just wedges again — they re-run **explicitly** (the Re-run
  button mints a fresh job). `SKIP LOCKED` so it never fights a worker finalizing a job.
- **The worker reaps at two moments** (`job_worker.py`): at **startup** with
  `older_than_seconds=0` (no worker is alive, so every `running` row is orphaned) — right
  after the run sweep — and **periodically** in the poll loop with
  `older_than_seconds = max_duration` (the watchdog bound; no legitimate run outlives it),
  which catches leases leaked while the worker keeps running. Each reaped RUN job also has
  its run reconciled to `interrupted`, so job and run never diverge.
- **The active-run query is lease-aware.** `latest_active_run_for_user` now counts a
  `running` job as active only while `locked_at` is fresher than the watchdog bound —
  belt to the reaper's suspenders, so a wedged run stops reading as "ongoing"
  *immediately*, even in the window before the next reap.

## Consequences

- A crashed/orphaned run can no longer masquerade as a perpetual "ongoing run"; the view
  reflects reality within one poll interval, and instantly via the lease-aware query.
- Job and run terminal states converge (both terminal after reconcile), so operator
  stats (`runner_healthy` in the ops endpoint) become truthful — the reaper clears the
  `stuck` count instead of it climbing forever.
- The existing six orphans are cleaned by the startup sweep on the next backend restart.
- A run that legitimately takes near `max_duration` is unaffected (its lease is fresh and
  the watchdog governs it); only leases *past* the bound — which mean a dead process — are
  reaped. The tradeoff is one config (`max_duration`) doubling as the "is this run still
  plausibly alive?" horizon, which is exactly its meaning.
