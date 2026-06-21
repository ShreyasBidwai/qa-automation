# ADR-0033: Role-based access control (owner / admin / member / viewer)

- Status: Accepted
- Date: 2026-06-21
- Deciders: Engineering

## Context

ADR-0032 makes the **organization** the tenancy root: projects belong to an org and
users join orgs through a membership. B3 now needs to say *what each member may do*.
We want a small, legible set of roles, one enforcement path used by every data
endpoint, and a leak-safe failure model.

## Decision

### Roles

A native `org_role` enum, ordered most→least privileged:

| role     | intent                                                            |
| -------- | ----------------------------------------------------------------- |
| `owner`  | full control of the org, including members/roles and deleting it  |
| `admin`  | manage members (but not owners), projects, runs, triage           |
| `member` | projects, runs, triage — the everyday contributor                 |
| `viewer` | read-only: view projects/runs/findings; no runs, triage, or edits |

### Permission matrix

Permissions are explicit; a role maps to a set of them. The source of truth is
`app/core/permissions.py`.

| permission        | owner | admin | member | viewer | guards what                          |
| ----------------- | :---: | :---: | :----: | :----: | ------------------------------------ |
| `VIEW`            |   ✓   |   ✓   |   ✓    |   ✓    | GET project / runs / findings        |
| `RUN`             |   ✓   |   ✓   |   ✓    |        | create run, ingest                   |
| `TRIAGE`          |   ✓   |   ✓   |   ✓    |        | triage findings (single + bulk)      |
| `MANAGE_PROJECT`  |   ✓   |   ✓   |   ✓    |        | create / update / delete project     |
| `MANAGE_MEMBERS`  |   ✓   |   ✓   |        |        | invite, change role, remove member   |
| `MANAGE_ORG`      |   ✓   |       |        |        | rename / delete the org              |

Two **target-aware** rules sit on top of `MANAGE_MEMBERS` (they cannot be expressed
as a role→permission cell because they depend on the *target's* role):

1. **Only an owner manages owners.** An admin may not change or remove a member
   whose role is `owner`, and may not grant the `owner` role. Owners can.
2. **An org always keeps ≥1 owner.** Demoting or removing the last `owner` is
   refused (409) regardless of actor.

### Enforcement model (leak-safe)

Every project/run/finding/triage endpoint resolves access through one helper
(`app/api/authz.py`). Given the caller and a required permission:

1. **Not authenticated** → `401` (unchanged, ADR-0030).
2. **Resource missing, or caller is _not a member_ of its org** → `404`. We do not
   leak that the resource exists to someone with no business knowing.
3. **Caller _is_ a member but the role lacks the permission** → `403`. They can
   already see the resource exists (they're in the org), so hiding it buys nothing;
   `403` is the honest, debuggable answer.

This is the deliberate **404-for-outsiders, 403-for-insiders** split. The same
split applies at the org level (non-member of an org → `404`; insufficient role →
`403`).

### Invites

Invitations reuse B2's reset-token discipline (ADR-0030): a 256-bit random token is
emailed, only its **SHA-256 hash** is stored, it is **single-use** (`accepted_at`)
and **expiring** (`expires_at`), and the raw token is **never logged or returned in
an API response** — it only goes out through the mailer. Accepting requires an
authenticated user and adds *that* user to the org with the invite's role
(possession of the secret token is the authorization, mirroring password reset).

## Consequences

- One code path (`authorize_project` / `authorize_org`) guards every data endpoint;
  the matrix lives in exactly one module and is unit-tested role × action.
- The 404/403 split is a tested invariant, not a per-endpoint judgement call.
- `viewer` is genuinely read-only; `member` is the default collaborator; `admin`
  runs the team day-to-day without being able to touch owners or delete the org;
  `owner` is the only role that can remove the org or manage owners.
- The last-owner guard means an org can never be orphaned into an unmanageable
  state by a role change or member removal.
