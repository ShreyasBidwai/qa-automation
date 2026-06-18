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
