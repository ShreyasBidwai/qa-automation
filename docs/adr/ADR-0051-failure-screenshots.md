# ADR-0051: Failure screenshots — capture, store behind one indirection, serve authorized

- Status: Accepted
- Date: 2026-06-24
- Deciders: Engineering

## Context

When a test fails during a run, a screenshot of the UI state is visual evidence the
UI (run dashboard + single-issue view) should show. The backend must capture it,
store the bytes, attach a reference to the finding, and serve it. Built now against
the current/stub path so it is ready when real Playwright runs execute. Screenshots
can contain sensitive app state (logged-in screens, real records), so serving is the
sensitive part.

## Decision

### Storage — local disk tonight, behind a SINGLE indirection

Bytes are stored on **local disk**, in a **gitignored** directory
(`screenshot_dir`, default `var/screenshots`, added to `backend/.gitignore`). No
object storage tonight. But every write/read goes through one module
(`app.screenshots`): `store_screenshot(bytes) -> ref` and `get_screenshot(ref) ->
bytes | None`. The ref is an **opaque key** (a uuid hex), never a path — call sites
never touch the filesystem, so swapping the backend is a one-module change. The
module carries `# TODO: swap to object storage at deploy`.

Local disk is sufficient only while capture and serve share a filesystem — true for
the in-process stub/demo path. Real multi-container Playwright runs (capture on the
runner, serve from the control plane) need object storage; the single indirection +
opaque ref are exactly what makes that swap mechanical.

### Capture — at the execution seam, best-effort, mirroring `evidence_ref`

`ExecutionResult` gains optional `screenshot: bytes | None` (a browser runner
provides bytes on failure; it has no DB access). `RunLifecycle`, for a **failing**
result carrying bytes, stores them via `store_screenshot` and records the ref on the
`results` row. The `FindingAssembler` then copies the representative result's
`screenshot_ref` onto the finding — the **same path `evidence_ref` already takes**.
So the new columns are `results.screenshot_ref` + `findings.screenshot_ref` (both
nullable; migration `0030_finding_screenshot`, linear off `0029`).

Capture is **best-effort and side-effect-safe**: it only fires for a failing result
with bytes, and any storage failure is logged, never raised — capturing a screenshot
can never break or fail a run (the same rule as incident capture). A passing result
attaches nothing.

The stub/demo executor stores a small generated placeholder PNG for its failing
finding, so the UI screenshot affordance can be built + demoed before real execution.

### Serve — authorized endpoint only, never a public path

`GET /findings/{id}/screenshot` reads the bytes through `get_screenshot` and streams
them as `image/png` **only after authorizing VIEW on the finding's project**. It is
NEVER served from a static/public folder or a raw filesystem path. Responses:

- **404** — unknown finding, a finding in a project the caller can't access
  (existence not leaked, ADR-0033), or a finding with no screenshot.
- **403** — the caller is in the org but the role lacks VIEW.
- **200** `image/png` — authorized + a screenshot exists.

The finding payload exposes `has_screenshot: bool` (true iff `screenshot_ref` is
set), so the UI knows whether to show the affordance without fetching bytes. Additive
— no existing payload shape changes.

## Consequences

- Findings carry visual failure evidence end-to-end; the UI shows it via one
  authorized fetch, never inline and never from a public path.
- Screenshot capture is invisible to the run: a store failure degrades to no
  screenshot, logged; the run proceeds and commits exactly as before.
- The local-disk impl is a deliberate tonight-only choice; the indirection + opaque
  ref keep the object-storage swap to two functions.
- `screenshot_ref` lives on both `results` (capture point) and `findings`
  (propagated), exactly like `evidence_ref` — no new flow, no bytes in the DB.
