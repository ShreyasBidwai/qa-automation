# ADR-0043: Cross-layer DB-state testing (safety-first)

- Status: Accepted
- Date: 2026-06-22
- Deciders: Engineering

## Context

Testing has verified "the API response is right" and mapped the cross-layer blast
path (page→endpoint→model→table, ADR-0041). B10 deepens it to "the DATABASE landed
in the right state" — the table end of that path: after a POST creates an order,
assert the `orders` row exists with the right columns; after a soft-delete, assert
the row is flagged, not gone. Asserting DB state means *connecting to a database and
reading (and, for full coverage, writing) it* — which is dangerous if that database
is ever a real one. The design is therefore safety-first.

## Decision

### The load-bearing safety rule — never a production database

DB-state testing NEVER runs against a production (or staging) database. Full stop.
`gate.ensure_disposable` is a structural hard gate with three independent checks,
all required:

1. the target carries an **explicit** `disposable=true` flag (intent is mandatory —
   absent/false is refused);
2. nothing in the URL looks prod/staging (`prod`, `production`, `live`, `staging`,
   `stg` in host or db name → refused **even if** flagged — a mislabel can't slip
   through);
3. the target is a local host **or** affirmatively name-marked disposable
   (`disposable`/`throwaway`/`ephemeral`/`dbstate`/`scratch`) — an unrecognized
   remote target is refused (err toward refusing).

It raises `ProdTargetRefused`, which is **never** caught-and-continued. Every write
path funnels through `DbStateExecutor.ensure_writable`, which calls the gate — there
is no write-to-disposable-DB path that skips it. The provisioner gates the target
*before* any `CREATE DATABASE`, so a prod-named DB is never even created. This is the
B10 equivalent of B8's "never heal an assertion": model-free, structural, tested
directly, biased toward refusing.

### Disposable provisioning, tiered + opt-in

DB-state testing runs against a **fresh disposable database provisioned from the
target app's migrations** (`DisposableDatabase`), reset (truncate) between runs,
dropped when done — never the app's real/staging data. It is opt-in per project via
`projects.db_state_tier` (migration 0025, validated string, default `off`):

- **off** (default) — no DB-state testing happens at all;
- **read_only** — SELECT table-state assertions only; writes to the disposable DB
  are structurally refused;
- **full** — writes permitted, but ONLY through the non-prod gate above.

Changing the tier is RBAC-gated (`MANAGE_PROJECT`); raising to `full` records intent
only — the gate is enforced at execution time, so flipping the tier can never by
itself write to a real DB.

### Oracles tagged honestly, tied to the table node

A check asserts `row_present` / `row_absent` / `column_equals` / `soft_deleted`,
identifier-validated and fully parameterized. Its trust is tagged honestly:
`rule-derived` when the expectation follows from a schema constraint or documented
rule, `characterization` when it merely pins current observed state (the honest
default). The check is tied to the Brain's table node (`table_node_id`), so the
blast path is **verified at the table end**, not just mapped.

### Honest about the limit — rollback ≠ universal safety

Transactional rollback undoes the **disposable database only**. It does NOT undo
real-world side effects — emails, payments, third-party API calls. So `full` mode is
safe ONLY against a non-prod target whose integrations are sandboxed or stubbed. We
state this plainly and never imply that DB rollback makes `full` mode universally
safe. The non-prod gate protects the *database*; it does not protect the *outside
world*, which is why `full` is opt-in, gated, and documented as requiring a
sandboxed target.

## Consequences

- The safety gate is hermetic and in the fast suite (`make test`) — safety-critical
  code is never behind an optional lane. The real disposable-DB provisioning is the
  execution edge and runs in a new heavy lane (`db_state`, `make test-db-state`).
- DB-state assertions complete the cross-layer story: a finding can now say "the row
  did/didn't land", not only "the response was wrong".
- The honesty about side effects keeps `full` mode from being mis-sold as risk-free;
  it is a deliberate, gated, non-prod-only capability.
