# ADR-0057 — Concurrent `claude -p` via a refresh-safe bridge gate

## Status

Accepted.

## Context

Test-case generation is the slowest phase of a run: mode_b renders one PHPUnit test
per case by calling the AI provider, and for a real target (~50 endpoints) that is
minutes of wall time. The bottleneck is **serial AI calls**.

The production provider is the host **Claude bridge** (`app/bridge/server.py`,
ADR-referenced by `docs/running-real.md`): the runner POSTs `{prompt, model}` to a
host daemon that runs `claude -p` as the logged-in user, so the container never
mounts `~/.claude`. The bridge historically **serialized every call** behind one
global lock — not for throughput reasons, but because two `claude` processes that
both refresh the OAuth token at once invalidate each other's single-use refresh
token and log the host out.

The API providers (`anthropic_api`, `gemini`) can be called concurrently, but the
operator's constraint is to keep using `claude -p` (their subscription), no API key.
So the speed-up must come from making the bridge concurrent **without** reintroducing
the refresh race.

## Decision

Replace "one lock around every call" with a **reader/writer concurrency gate**
(`ConcurrencyGate`) that separates *using* a valid token (safe concurrently) from
*refreshing* it (must be serial):

- **Readers** — normal calls run concurrently, bounded by a `Semaphore(N)` where
  `N = CLAUDE_BRIDGE_CONCURRENCY`.
- **Writer** — the **first call of each "stale window"** is promoted to run
  **exclusively**: it drains in-flight readers, blocks new ones, and runs alone.
  That call refreshes the token as a side effect; the window is then "warm", so the
  next N calls run concurrently against the fresh token and **never trigger a refresh
  themselves**. A refresh therefore only ever happens with no peer running — the race
  is impossible.

Single-flight is enforced with a `Condition` + a `_warming` flag; the warm window is
`CLAUDE_BRIDGE_WARM_INTERVAL` seconds. `CLAUDE_BRIDGE_CONCURRENCY == 1` (the default)
short-circuits to the exact prior serial behaviour — a **zero-risk default**; the
operator opts into `N > 1`, and can revert to `1` instantly if they ever observe auth
churn.

On the generator side, a target's cases are now rendered with
`asyncio.gather(asyncio.to_thread(render_script, …))`: the blocking, synchronous AI
call runs off the event loop, so the fan-out is real. `render_script` is pure (no DB
or session) and the usage collector's `list.append` is atomic under the GIL, so this
is race-free; **all DB work stays on the one session, serial**.

## Consequences

- **Faster generation** on the subscription with no API key — `N=6` turns a
  ~12-minute 50-target generation into ~2–3 minutes, bounded by Anthropic's own rate
  limits (the existing bounded-retry/backoff absorbs 429s).
- **Output quality is unchanged.** Every call is still `claude -p --model … <prompt>`;
  concurrency changes *timing only*, never the prompt, model, or output. Test *quality*
  is a separate axis (spec-grounding, richer context) tracked elsewhere.
- **Safety is opt-in and reversible.** Default `1` = today's behaviour. The refresh
  race is structurally prevented at `N > 1`, not merely made less likely.
- **Follow-up:** cross-target fan-out (running multiple targets' generation
  concurrently, not just a target's cases) needs per-target sessions and a concurrency
  audit of the progress emitter + merge engine; it is deferred to its own change. The
  bridge gate + concurrent render land first, since they are the enabler and are safe.

## Alternatives considered

- **Switch to `anthropic_api` for concurrency** — rejected: the operator must keep
  `claude -p` (subscription, no key).
- **A pool of independent `claude` credential copies** — rejected: OAuth refresh
  tokens rotate (single-use), so a copy that refreshes invalidates the canonical login.
  The reader/writer gate keeps a single canonical credential and never lets two
  processes refresh at once.
- **Keep serial, just raise the token budget / model tier** — doesn't address the
  wall-clock bottleneck (serial calls).
