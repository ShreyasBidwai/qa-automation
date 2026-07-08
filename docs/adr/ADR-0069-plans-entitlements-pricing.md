# ADR-0069 — Plans, entitlements, and a hybrid seats + run-credits pricing model

## Status

Accepted. First slice of the commercial layer (Initiative B). Consumed by the quota
guard (B3, forthcoming) and the billing surfaces (B4/B5).

## Context

The platform has no commercial model: `organizations` carries only `name` +
`is_personal` (+ `suspended_at`, ADR-0068), and no quota, plan, seat, or billing
concept is enforced anywhere (the only rate limiting is per-IP on auth, ADR-0046). To
go to market we need plans, per-plan entitlements/quotas, and a place to attach them.

Our unit economics are unusual and advantageous: Polaris is *agentic*, so the real
cost-of-goods is AI token spend per run, which we already capture as **actual billed
cost per run** (`ai_usage.total_cost_usd`, ADR-0049). That lets us price a metered
unit at a known margin — most competitors meter a proxy because they can't see true
cost. The market (mabl, Katalon, Qase, Autify) has converged on a **hybrid** shape: a
per-seat base for interactive use + a usage/credit pool for the compute-heavy agentic
work (mabl meters cloud runs as credits; Katalon is per-seat; Qase is seats + AI
credits with overage).

## Decision

Introduce a **plan catalog** + **per-org plan assignment** + a pure **entitlements
resolver**. Pricing is hybrid: seats (people) + run-credits (the metered unit, sized
to a run's measured AI cost).

- **`plans`** — a seeded catalog table, one row per tier, keyed by a stable `key`
  (`free` / `team` / `business` / `enterprise`). Columns carry the entitlements:
  `price_per_seat_monthly_usd` (NULL = custom / "contact us"), `included_run_credits_monthly`,
  `max_projects`, `max_seats`, `max_parallelism`, `retention_days` (NULL on a quota =
  unlimited), a `features` JSONB (flexible flags: SSO, priority support, …),
  `is_public`, and `sort_order`. A table (not a hardcoded enum) so quotas are tunable
  and admin-manageable without a migration.
- **`organizations.plan_key`** — a string defaulting to `free`; existing orgs backfill
  to `free`. A string key (not an FK) keeps the fallback trivial and the catalog
  editable; the resolver treats an unknown/absent key as `free`.
- **Entitlements resolver** (`app.core.entitlements`) — pure, DB-free given a Plan:
  `plan_allows(plan, ...)` / quota lookups. The org→plan join lives in a repository;
  the *decision* logic is pure and unit-tested, mirroring `app.core.permissions`.
- **Seed tiers** (indicative launch numbers, grounded in the 2026 market scan —
  refine before launch):
  | key | seat/mo | credits/mo | projects | seats | parallel | retention | notable |
  |-----|---------|-----------|----------|-------|----------|-----------|---------|
  | free | $0 | 50 | 1 | 2 | 1 | 7d | PLG trial |
  | team | $49 | 1,000 | 5 | 10 | 3 | 30d | email support |
  | business | $99 | 5,000 | 25 | 50 | 10 | 90d | SSO, priority |
  | enterprise | custom | unlimited | unlimited | unlimited | 25 | 365d | SAML, dedicated |

## Consequences

- The quota guard (B3) reads the org's effective plan at the **enqueue choke point**
  (the durable queue — the single place "may this org run?" is answerable), where it
  will also honour the ADR-0068 suspension. Soft-limit + overage for paid plans; a hard
  stop for free.
- Metering (B2) sums the already-captured per-run AI cost into per-org/period rollups
  and debits run-credits ∝ measured cost — margin-safe because the cost is real.
- The plan catalog powers both the customer pricing page (B5) and the operator billing
  console (B4); `is_public` hides internal/legacy tiers.
- Numbers are seeded, not hardcoded, so pricing iterates without code changes. The
  table is intentionally coarse now (one metered unit: run-credits) — richer metering
  (per-parallel, per-seat overage) can extend the columns additively later.
- No secret or payment data lives here; Stripe (B6) integrates later and never stores
  card data in our DB (tokens/customer-ids only).
