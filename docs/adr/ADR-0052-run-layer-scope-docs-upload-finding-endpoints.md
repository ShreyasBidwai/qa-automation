# ADR-0052: Run layer scope, document upload, and two finding-endpoint follow-ups

- Status: Accepted
- Date: 2026-06-24
- Deciders: Engineering

## Context

Four additive, backward-compatible follow-ups that the frontend needs. Items 1 and 2
were verify-first; what already existed is recorded below.

## Decisions

### 1) Layer scope on run-create (ADDED — none existed)

Verified: `ModeBRunRequest` had only `mode`/`strategy`/`changeset`/`max_targets`, and
the domain `RunRequest` carried no layer field. **Added** an optional `layers` scope:

- `ModeBRunRequest.layers: list["ui"|"api"|"db"] | None = None` — omitted/null = the
  full set (existing behaviour unchanged); a given list is deduped and must be
  non-empty. Threaded through `RunRequest.layers` (and the durable job payload, so it
  survives a restart — no schema change, it rides the existing JSONB payload).
- Honored in **planning** (`ModeBOrchestrator`): a layer maps to a target kind —
  **ui → page**, **api → endpoint** — so the selected targets are filtered to the
  requested layers *before* the count bound (`selection.targets_for_layers`). **db**
  has no target kind: it gates the **DB-state phase** (run only when `db` is in
  scope). `layers=None` ⇒ unfiltered targets + DB phase as before.

No migration (runtime param on the JSON payload).

### 2) Document upload (ADDED upload path — store/list/delete already existed)

Verified: `app/api/documents.py` already exposes `POST /projects/{id}/documents`
(JSON `{title, doc_kind, content}`), `GET .../documents` (list), and
`DELETE .../documents/{id}`, all RBAC-gated (MANAGE_PROJECT to mutate, VIEW to list)
and running the B9 chunk→embed pipeline (`DocumentService`) + spec reconciliation.

**Added** the missing **file-upload** path, additively (the existing JSON POST is
unchanged): `POST /projects/{id}/documents/upload` (multipart) — reads the UTF-8 text
body and **reuses `DocumentService.add_document` + `reconcile_document`** (no
re-implementation of embedding). MANAGE_PROJECT. 400 on non-UTF-8/empty, 413 over the
B9 size cap, 422 on an unknown `doc_kind`. **Best-effort embed:** an `EmbeddingError`
is caught and surfaced as a clean **502**; because the request session rolls back on
any exception, a failed embed leaves the project **untouched** (no orphan document or
chunks). Adds the `python-multipart` runtime dependency (FastAPI needs it for
`UploadFile`/`Form`). No migration (reuses the B9 tables).

### 3) `GET /findings/{id}` (ADDED — none existed)

Verified: no direct single-finding fetch (the single-issue UI reconstructed it from
run/inbox scans). **Added** `GET /findings/{id}` returning the full `FindingResponse`
(incl. `has_screenshot`) by reusing the run-dashboard builder (detail + triage +
heal-supersede). Authorized VIEW on the finding's project; **404** for unknown or
inaccessible (existence not leaked) — the same by-id pattern as the screenshot
endpoint.

### 4) Server-side project filter on `GET /findings` (ADDED param)

Verified: `GET /findings` hardcoded `open_findings(None, …)` even though
`OpenFindingsReader.open_findings` already accepts a `project_id`. **Added** an
optional `project_id` query param threaded through, so the inbox project filter
narrows the **whole result set + total** server-side, not just the current page. It
still rides the caller's org scope (`org_ids`), so a project the caller can't view
yields nothing (existence not leaked). Omitted ⇒ unchanged global inbox.

(Severity/layer/trust/status filters were considered but are NOT cheap here — the
reader's selection doesn't support them — so only `project_id`, the required one, is
added.)

## Consequences

- A run can be scoped to UI/API/DB layers; omitting `layers` is byte-for-byte the old
  behaviour.
- Documents can be attached by file upload through the existing B9 pipeline; an embed
  failure can never corrupt a project.
- The single-issue view has a direct finding fetch; the inbox project filter is
  correct across the full result set, not just one page.
- No migrations — every change is additive on existing storage.
