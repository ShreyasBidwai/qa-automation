# ADR-0032: Organizations own projects (team tenancy), with a personal org per user

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

B2 (ADR-0031) made projects **user-owned**: `projects.owner_id` → `users.id`,
NULL = legacy/shared, access = owner-or-shared. B3 turns the product into a
**team** product: real customers are organizations, several people collaborate on
the same projects, and access is governed by a role within the team. The tenancy
root has to move from the individual user to the organization.

Three things must be decided and preserved across the move:

1. **The model.** How orgs, users, and projects relate.
2. **Solo users.** A single person must keep working with zero ceremony — no
   "create a team first" wall.
3. **The migration off 0018.** Existing owned projects, and the legacy NULL-owner
   ("shared") projects, must land somewhere sensible without data loss and
   **without staying globally shared** under the new model.

## Decision

**Organizations own projects; users join organizations through a
membership-with-role; every user gets a personal organization on signup.**

### Model

- `organizations` — a team. `is_personal` marks the auto-created solo workspace.
- `organization_members` — `(org_id, user_id, role)`, unique on `(org_id, user_id)`
  (one membership per user per org). `role` is the ADR-0033 enum.
- `organization_invites` — pending email invitations (see ADR-0033 for the token
  discipline).
- `projects.org_id` → `organizations.id` (**NOT NULL** after backfill, `ON DELETE
  CASCADE`): a project always belongs to exactly one org.
- `projects.owner_id` is **renamed to `created_by`** (nullable, `ON DELETE SET
  NULL`). It no longer governs access — `org_id` does — but the "who first created
  this" provenance is worth keeping for audit/UX, so we preserve the value rather
  than drop the column.

### Personal org on signup

`AuthService.sign_up` creates a personal org (`is_personal=true`) and an `owner`
membership for the new user, atomically with the user + session. A solo user
therefore always has exactly one org they own; `POST /projects` with no `org_id`
targets it. Nothing about the single-user flow changes from the user's point of
view.

### Migration off 0018 (linear, forward-only, data-preserving)

`0019` runs a one-time backfill (all in the migration, deterministic):

1. For each existing user (ordered by `created_at, id`): create a personal org,
   an `owner` membership, and set `org_id` on **their** owned projects.
2. **Legacy NULL-owner projects** are assigned to a single dedicated **`Legacy`
   org**, owned by the **earliest user** (so someone can administer the previously
   shared data). They are explicitly *not* left globally visible — the org model
   has no "shared by everyone" state, and silently dumping them into one person's
   *personal* org would misrepresent them. A dedicated Legacy org keeps them
   grouped and clearly labelled. (If the database has legacy projects but *no*
   users at all, the Legacy org is created with no members — the data is preserved
   and adoptable once someone is added; documented, not silently shared.)
3. `projects.org_id` is set `NOT NULL` (every row now has one).

No rows are deleted; `created_by` retains the old `owner_id` value.

## Why a Legacy org (not the earliest user's personal org)

The two candidates were "a dedicated Legacy org" and "fold legacy projects into the
earliest user's personal org". A personal org is, semantically, *that person's solo
workspace*; pre-auth shared demo data is not their personal work, and mixing it in
makes the personal workspace lie. A dedicated, clearly-named `Legacy` org keeps the
provenance honest, groups all legacy data in one place, and still gives the
earliest user ownership to triage/redistribute it. The cost is one extra org row,
which is negligible.

## Consequences

- Access is uniform: "is the caller a member of the project's org, and does their
  role permit the action?" (ADR-0033). Owner-or-shared logic is retired.
- Deleting an org cascade-deletes its projects (and their runs/findings). That is
  the only destructive path and is owner-gated (ADR-0033); personal orgs cannot be
  deleted.
- `created_by` is informational only; never an access check. New projects are
  stamped with both `org_id` (tenancy) and `created_by` (provenance).
- The migration is idempotent in effect (each project ends in exactly one org) and
  preserves every row; it is covered by a dedicated migration test that seeds a
  0018 database and asserts the post-0019 shape.
