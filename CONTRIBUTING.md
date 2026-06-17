# Contributing

This guide covers how we branch, commit, and open pull requests. It is a
summary of [`docs/04-engineering-standards.md`](docs/04-engineering-standards.md)
§2–3 — when in doubt, that document wins (unless an ADR overrides it). Everything
here applies equally to human- and agent-written code.

## Branching — trunk-based GitHub Flow

- `main` is always green and deployable. **No direct pushes to `main`; PRs only.**
- Work happens on **short-lived branches off `main`**, deleted after merge.
- Branch names follow `type/scope-short-desc`, using the same `type` set as
  commits below. Examples:
  - `feat/backend-health`
  - `fix/runner-timeout`
  - `chore/repo-scaffold`
  - `docs/adr-dual-db`

## Commits — Conventional Commits

Every commit message follows
[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short, imperative summary>

<optional body — what & why, wrapped at ~72 cols>

<optional footer — BREAKING CHANGE:, refs #issue>
```

Allowed **types** (Standards §3):

| Type       | Use for                                                        |
|------------|----------------------------------------------------------------|
| `feat`     | A new feature or capability                                    |
| `fix`      | A bug fix                                                       |
| `chore`    | Tooling, scaffolding, deps, config — no product behavior change |
| `test`     | Adding or correcting tests                                     |
| `docs`     | Documentation only (incl. ADRs)                                |
| `refactor` | Code change that neither fixes a bug nor adds a feature        |

Guidelines:

- Use the imperative mood: "add", not "added"/"adds".
- Keep the summary ≤ ~72 characters; no trailing period.
- Scope is optional but encouraged (`feat(planner): …`, `fix(runner): …`).
- Breaking changes: add a `!` after the type/scope (`feat!: …`) **and** a
  `BREAKING CHANGE:` footer.

Examples:

```
feat(backend): add /healthz and /readyz endpoints
fix(runner): tear down test DB when a run is cancelled
chore: scaffold monorepo structure
docs(adr): record dual-DB execution decision
```

## Pull requests

- **Small and single-purpose** — ideally one task per PR.
- The PR description states: what it does, the **linked task/issue**, **what's
  tested**, and **what's deferred** (Standards §3).
- Keep contracts honest: changes to anything marked a "contract" in the docs
  require a new ADR in [`docs/adr/`](docs/adr/) (Standards §19).

### Required to merge (Standards §3, §20 — Definition of Done)

- [ ] Review approved
- [ ] Full CI green (build → lint → typecheck → unit → integration → E2E where relevant)
- [ ] No unresolved review threads
- [ ] Works in `docker compose up`
- [ ] Tests added for changed code; meaningful assertions, no flakes
- [ ] **No secrets** in code, logs, or VCS
- [ ] Logging / health / graceful start-stop honored where relevant
- [ ] Docs/ADR updated if a contract changed
- [ ] Tracker note added

## Code style

- **Python:** ruff (lint) + black (format) + mypy (strict on new modules); type-hint all public APIs.
- **TS/React:** eslint + prettier; strict TS; no `any` without justification.
- No dead code, no commented-out blocks, no TODOs without an issue reference.

## Pre-commit hooks

Install the hooks once so lint/format runs before every commit (mirrors CI):

```bash
pipx install pre-commit   # or: pip install pre-commit
pre-commit install        # from the repo root

# The frontend hooks (eslint/prettier) use the project's own tooling, so install
# its deps once. The backend hooks (ruff/black) are self-contained.
cd frontend && npm ci && cd ..
```

What runs (see [`.pre-commit-config.yaml`](.pre-commit-config.yaml)): ruff + black
on `backend/**`, eslint + prettier on `frontend/**`, plus basic hygiene checks.
Run on everything manually with `pre-commit run --all-files`.

## CI

Every push and PR runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml),
which executes the same `make` targets locally used — entirely in Docker, so
there is no environment drift:

`make build` → `make lint` → `make test` (pytest → vitest → playwright, with the
backend services coverage gate) → coverage/test-report artifacts, plus a
parallel `make audit` (pip-audit + npm audit) for dependency scanning.

**No-merge-on-red:** configure branch protection on `main` to require the
**“CI success”** status check (and review approval). That single check is green
only when every CI job passed.

## Maker–Checker

Tasks are implemented by a *maker* and independently verified by a *checker*
against the acceptance criteria and the engineering standards (Standards §21). A
task is accepted only once the checker passes it.
