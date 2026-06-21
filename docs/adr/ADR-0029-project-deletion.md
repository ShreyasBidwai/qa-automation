# ADR-0029: Project deletion is a soft-delete

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

`DELETE /projects/{id}` is needed for project management. A project is the tenancy
root: every run, result, finding, triage record, and Brain node hangs off it
(`project_id` FK, `ON DELETE CASCADE`). The choice is **hard cascade delete** vs
**soft delete**, and the sprint guidance is to lean to whichever **loses less
history safely**.

## Decision

**Soft-delete.** `DELETE /projects/{id}` sets a `deleted_at` timestamp; it removes
nothing. A new nullable `projects.deleted_at` column (migration 0016) records when.

- **Reads exclude soft-deleted projects.** `ProjectRepository` filters
  `deleted_at IS NULL` on `get` / `get_by_slug` / `list` / `count`, so every
  existing caller (get-project, create-run, ingest, triage, the open-findings
  aggregation) treats a deleted project as **absent → 404 / excluded** with no
  per-call change.
- **Idempotent.** Deleting an already-deleted (or unknown) project is a 404.
- **Response:** `204 No Content`.

All history (runs, findings, triage) is preserved and the delete is reversible
(clear `deleted_at`) — undelete/purge endpoints are a later nicety, not built now.

## Why not hard cascade

A hard `DELETE` cascades to every run, result, finding, and triage decision for the
project — irreversible loss of exactly the history this product accumulates (the
"Brain" and triage are compounding assets). A mis-click or a wrong id would be
unrecoverable. Soft-delete loses no history, is reversible, and keeps audit/debug
trails — strictly the safer default for local/demo/internal use, and the right
base for multi-user deletion semantics in B2+.

## Consequences

- One nullable column; reads centralised in `ProjectRepository` already, so the
  filter lives in one place.
- Slugs of deleted projects still occupy the unique index (a re-create with the
  same name gets a fresh unique slug suffix anyway, so this is a non-issue).
- A future hard-purge (GDPR/erasure) builds on this by hard-deleting rows where
  `deleted_at` is set — additive, behind an explicit destructive action.
