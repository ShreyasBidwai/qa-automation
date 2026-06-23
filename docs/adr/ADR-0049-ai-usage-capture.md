# ADR-0049: Per-run AI usage + actual billed cost capture from the `claude -p` CLI

- Status: Accepted
- Date: 2026-06-23
- Deciders: Engineering

## Context

We invoke the model through the Claude CLI (`claude -p`), not the raw API. The usage
investigation (preceding read-only task) established that the installed CLI
(v2.1.186) returns, with `--output-format json`, a single stdout envelope carrying
both the model output and the **actual billed usage** of the invocation:
`total_cost_usd`, a `usage` block (`input_tokens`, `output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`), and a per-model
`modelUsage` rollup with `costUSD`. We previously invoked `claude -p --model <m>`
with plain stdout and captured nothing. This ADR wires capture (no UI — display is
deferred until real data exists).

## Decision

### Capture at the CLI seam, best-effort

`ClaudeCliProvider._invoke` now passes `--output-format json` and parses the envelope
(`app/ai/usage.parse_envelope`). The call's external behaviour is unchanged — callers
still receive only the model text (the envelope's `result`); parsing is internal.

Capture is **strictly best-effort and cannot break or alter generation**
(same rule as incident capture):

- `parse_envelope` NEVER raises. Malformed JSON, a non-object, a missing `result`,
  or a missing `usage` block falls back to treating stdout as the model text and
  flags usage **unavailable** (`usage_available = false`, token/cost columns NULL).
- The envelope's own `is_error` is surfaced honestly on the record, not swallowed.
- The persist step (`mode_b._flush_usage`) runs in a SAVEPOINT and swallows any
  failure — a failed usage write rolls back only itself and leaves the run's
  transaction (findings/score/classify + the caller's commit) intact.

### Attribution without coupling the synchronous provider to the run

Providers are synchronous and run-agnostic, and in an autonomous run generation
happens **before** the run row exists (`_ensure_cases` precedes `RunLifecycle`). A
`contextvars`-backed `UsageCollector` bridges the two: the orchestrator installs a
collector for the duration of a run, provider calls append `(phase, CliUsage)` to it,
and the orchestrator drains + persists once `run_id` exists. ContextVars are
per-asyncio-task, so concurrent runs never cross-attribute. A provider call with no
collector installed (e.g. an authoring path) is a silent no-op — capture is wired at
the autonomous-run seam for now; other phases opt in by establishing a collector.

The stub provider records a flagged-unavailable entry too, so the capture seam fires
under the hermetic suite (the aggregate counts the call; cost/tokens stay null).

### Persistence: per-call records as the source of truth; aggregate computed

`ai_usage` stores one row per invocation (run_id, phase, model, the four token
counts, `total_cost_usd`, `model_cost_usd`, `usage_available`, `is_error`) — an
observability log keyed by `project_id`/`run_id` with no FK, like `incidents`. The
**per-run aggregate** (totals + per-phase + per-model) is COMPUTED over those records
(`AiUsageRepository.aggregate`), not stored as a denormalized summary — so it can
never drift from the records it summarizes; a run's record set is small, so the
rollup is one read + an in-memory fold. Read via `GET /runs/{run_id}/usage`
(authorized VIEW; records + aggregate). Additive — no existing payload shape changes.

Migration `0028_ai_usage` (linear off `0027_run_numbers`). Cost is `Numeric(14, 8)`,
comfortably holding the CLI's ~7-significant-figure dollar values without float drift.

## Honest semantics — what `total_cost_usd` means

`total_cost_usd` is the **REAL billed cost of OUR CLI invocation**. It is NOT a clean
prompt+completion API cost: invoking via `claude -p` includes the Claude Code
harness's own system prompt, tool schemas, and prompt caching, so the figure covers
all of that. Consequently:

- It is the honest "what this call cost us to invoke through the CLI" — the right
  number for per-run cost attribution of our actual path.
- It **varies with cache warmth**: a probe showed `input_tokens: 10` of genuinely new
  input against `cache_read_input_tokens: 17659` / `cache_creation_input_tokens: 7384`
  of harness/session context. We therefore record `cache_read`/`cache_creation`
  **separately** from `input_tokens` so the breakdown is legible and the cache effect
  is visible rather than hidden inside one number.
- It must not be relabeled as anything other than actual invocation cost. Total tokens
  processed for a call = `input + cache_read + cache_creation + output`.

fastembed embeddings are local and free — no tokens, no dollar cost, nothing to
capture here. There is no Gemini / second-LLM path to instrument.

## Consequences

- We now record the actual billed cost + token breakdown of every autonomous-run
  model invocation, attributed to run + phase — no estimation, no price table.
- Capture is invisible to generation: parse failures degrade to flagged-unavailable
  records; a persist failure is isolated by a savepoint. The run is never affected.
- The aggregate is always consistent with the records (computed, not stored).
- Display is intentionally deferred (CAPTURE ONLY) until the data is real.
