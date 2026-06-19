# Architecture Decision Records (ADRs)

This folder holds numbered Architecture Decision Records. Anything marked a
**"contract"** in `01-architecture.md` / `03-trd.md` may only change via an ADR
(Engineering Standards §19).

## Conventions

- One file per decision: `ADR-NNNN-short-slug.md` (zero-padded, e.g. `ADR-0001-monorepo.md`).
- Numbers are sequential and never reused.
- Each ADR records **Context → Decision → Consequences** and carries a status.
- Statuses: `Proposed` → `Accepted` → (later) `Superseded by ADR-NNNN` / `Deprecated`.
  Superseding replaces, never edits, the old record.

## Template

```markdown
# ADR-NNNN: <title>

- Status: Proposed | Accepted | Superseded by ADR-NNNN
- Date: YYYY-MM-DD
- Deciders: <names/roles>

## Context
<the forces at play: problem, constraints, options considered.>

## Decision
<the choice made, stated plainly.>

## Consequences
<what becomes easier, what becomes harder, follow-ups.>
```

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0001](ADR-0001-monorepo.md) | Monorepo | Accepted |
| [ADR-0009](ADR-0009-projectstore-abstraction.md) | ProjectStore abstraction | Accepted |
| [ADR-0010](ADR-0010-sha-keyed-cache-invalidation.md) | SHA-keyed cache invalidation | Accepted |
| [ADR-0011](ADR-0011-test-case-lineage-versioning.md) | Test-case lineage versioning | Accepted |
| [ADR-0012](ADR-0012-regeneration-merge-and-proposals.md) | Re-generation merge with clobber-protection | Accepted |
| [ADR-0013](ADR-0013-proposal-resolution.md) | Proposal resolution (accept / reject) | Accepted |
| [ADR-0014](ADR-0014-mode-a-authoring-and-deterministic-scripting.md) | Mode A authoring + deterministic-first scripting | Accepted |
| [ADR-0015](ADR-0015-runtime-crawler-vs-source-adapter.md) | Runtime frontend crawler vs source adapter | Accepted |
| [ADR-0016](ADR-0016-auth-strategy-and-challenge-log.md) | Pluggable AuthStrategy + interim manual OTP + challenge log | Accepted |
| [ADR-0017](ADR-0017-ui-oracle-model.md) | UI oracle model for generated E2E tests | Accepted |
