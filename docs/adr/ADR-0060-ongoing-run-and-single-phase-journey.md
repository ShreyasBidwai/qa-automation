# ADR-0060 — The Ongoing-run view + a single-phase run journey

## Status

Accepted.

## Context

The live run view (ADR-0050) rendered the whole journey as one vertical spine — every
phase (Understand → Generate → Execute → Explore → Review) stacked, each with all its
steps. For a real run (generation over ~50 targets, a crawl over many pages) that is a
long, ever-growing scroll: the operator loses the current step in the noise, and there
is no single place to answer "what is running right now?". Two gaps:

- **No "current run" entry point.** Runs are project-scoped; to watch the run in
  progress you had to know its project, open the runs list, and click through. There
  was no global "the run happening now" view.
- **Everything at once.** The spine showed all phases and all steps together, and the
  tests a run authored were only visible on a separate Tests page, not where they were
  generated.

## Decision

**1. `GET /runs/active` + an Ongoing-run tab.** A new endpoint returns the caller's
newest still-active (queued/running) RUN job across their projects, org-scoped so it
never surfaces another tenant's run (`JobQueue.latest_active_run_for_user` joins
job → project → org member). A new primary nav entry "Ongoing run" (`/runs/ongoing`)
resolves it (`useActiveRun` polls until one appears, then PINS it so the view follows
that run to its end rather than flipping back to empty), and renders the journey.

**2. A single-phase journey (`RunJourney`).** The phase pipeline becomes a **tab
strip** (`role="tablist"`); the body shows only the **selected phase's** content, so
the page never grows unbounded and there is no cross-phase scrolling — each phase's
steps live in their own bounded, internally-scrolling panel. The tabs **auto-follow**
the active phase (the one holding the current step, else the last phase with events)
until the operator clicks a tab, which pins their choice. This is the default: you land
on the step that's happening now.

The same component powers BOTH the Ongoing-run page (a live run) and `/runs/{id}/live`
(replay of a finished run, reached via "Replay journey") — identical, since a finished
run replays from the same event stream and shows THAT run only.

**3. Tests where they're authored.** The Generate phase surfaces the tests the run
produced (reusing the Tests-viewer data), each with a **"View test"** button that opens
a drawer with the test's title, facets, the human-readable intent (lifted from the
renderer's `// Intent:` comment), and the code — the Playwright spec for a UI test, the
PHPUnit/Pest code for an API test. The live "browser window" frame stays with the
Explore-live-site (crawl) phase, where Polaris is actually driving the app.

## Consequences

- "What's running now?" is one click from anywhere; the view opens on the current step.
- A long run stays scannable — one phase at a time, no wall of steps.
- The tests a run authored are reviewable inline, in the phase that made them.
- `/runs/active` is one indexed query per poll; polling stops once a run is pinned, so
  the Ongoing tab isn't a busy-poll when a run is already on screen.
- Deferred: keyboard arrow-key navigation between tabs (they're focusable buttons with
  `aria-selected`, click/Enter/Space work); a multi-run "all active runs" view (the tab
  shows the single newest active run by design).
