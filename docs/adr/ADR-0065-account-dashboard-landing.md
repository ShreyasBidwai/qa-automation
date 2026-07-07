# ADR-0065 — Account dashboard as the post-login landing

## Status

Accepted.

## Context

After login the app dropped the user straight onto the flat **Projects** list. There
was no account-wide view — no "how healthy is everything?", no trend, no at-a-glance
triage of which projects need attention. Health only existed **per project**, one click
in. An operator with several projects had to open each to build a mental picture.

Two nearby run-view gaps compounded the "no overview" feeling and are folded into the
same slice:

1. A run's timeline showed the crawl phase **"Explore live site"** even for an
   **api-only** run that never crawls — an empty, misleading step.
2. A run surfaced its **failures** but never its **successes** — a fully-green run
   showed nothing affirming, and the new SKIPPED outcome (ADR-0064) wasn't visible.

## Decision

**A first-class account dashboard is the post-login landing (`/`, canonical
`/dashboard`).** It rolls up every project in the user's orgs for a chosen time window
and is deliberately visual: headline cards, a **pass-rate trend** (inline SVG area
chart), a **test-outcomes donut**, a **project-health table** (worst-first), and a
**recent-runs** feed. A **time-range filter** (7D / 30D / 90D / 1Y) re-scopes the trend,
outcome counts, and recent activity. If the account has **no projects**, the dashboard
hands off to **Projects** (which owns the empty/onboarding state), so a brand-new
account still lands somewhere it can act.

- **Backend** — `GET /account/dashboard?range_days=` (VIEW; org-scoped) in a dedicated
  `AccountDashboardReader` that **reuses the existing readers** (`ProjectSummaryReader`
  for per-project status/pass-rate/open-findings, `ResultRepository` outcome counts,
  `RunRepository`) and stays **batched** — a fixed number of queries regardless of
  project count (no N+1), the same load-bearing property the projects list already
  holds. It only ever reads the caller's orgs' projects (no cross-tenant leak).
- **Honesty carries through** — pass-rate excludes SKIPPED from both sides (ADR-0064),
  so a dashboard of un-verifiable endpoints reads "— / K unverified", never a lying 0%.
- **Charts are dependency-free** — small responsive SVGs that colour themselves from the
  design tokens via `text-…` + `currentColor`, so they track light/dark and never
  hard-code a hex; nulls in the trend break the line into honest gaps, never
  interpolated across days with no runs.

**Run-view fixes in the same slice.** The timeline's phase spine derives the crawl
("Explore live site") phase as **UI-only**: it appears only once the run actually
produced crawl events, so an api-only run's timeline no longer shows an empty step.
And the run dashboard gains an always-present **test-outcomes bar** (passed / failed /
errored / unverified) plus a **clean-run panel** that affirms a green run — success is
now shown, not just failure.

## Consequences

- The account has a real home: health, trend, and "what needs attention" in one view,
  with a filter to scope the window — useful and legible from the first login.
- New run views tell the whole truth of a run — its passes and skips, not only its
  failures — and an api-only run's timeline is no longer padded with a phase it never
  runs.
- The dashboard adds no new denormalised store; it composes existing readers, so it
  can't drift from the per-project and per-run numbers (one definition of pass-rate,
  ADR-0045/0064). The cost is a slightly heavier landing query — bounded and batched.
- A future iteration can add per-project / per-layer filters and a findings-over-time
  series; the reader's shape leaves room without a schema change.
