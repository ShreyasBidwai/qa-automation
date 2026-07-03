# ADR-0058 — CSV-authored tests (deterministic, QA-declared scenarios)

## Status

Accepted.

## Context

Polaris generates tests two ways today: **mode_b** (autonomous — plan cases from the
Brain, AI-render each) and **mode_c** ("describe it" — a natural-language prompt the
AI turns into authoring). Both lean on the AI provider, and both derive the oracle
from what the tool infers (characterization / rule-derived).

But a QA engineer often already knows the exact scenarios they want covered — "POST
`/api/v1/orders` with `{qty: 2}` must return 201", "the same with `{qty: 0}` must
return 422" — as a list. Forcing those through a prose prompt (mode_c) is lossy: the
model can misread the intent, invent a payload, or assert a value the QA never stated.
It is also non-reproducible (a re-run can render different code) and spends AI budget
to re-derive something the human already specified precisely.

There was no first-class way for a human to hand Polaris a **table of exact scenarios**
and get back runnable, persisted tests.

## Decision

Add a **CSV import** path for QA-authored scenarios, surfaced in the "Describe what to
test" section of the run form (`POST /api/v1/projects/{id}/tests/import`, multipart,
`MANAGE_PROJECT`).

Key choices:

- **Deterministic rendering, no AI.** The QA fully specifies the request (method, path,
  payload) and the expected status, so each row is rendered to a runnable PHPUnit/Pest
  test in pure Python (`app/generation/csv_import.py`) — the same dialect the executor
  already runs. This is reproducible (same CSV → byte-identical tests), free (no
  budget), and cannot hallucinate an assertion. The AI seam is deliberately absent.
- **Honest oracle = `spec-grounded`.** The QA *declared* the expected outcome, so the
  case is `oracle_source=spec-grounded`, `authored_by=human`, `origin=authored`. This
  is the one path where spec-grounded is earned without an ingested requirement doc —
  the CSV *is* the stated requirement. (The AI planner still forbids spec-grounded; see
  `test_nothing_is_spec_grounded`.)
- **Reuse the merge engine.** Rows persist through the same `CaseMergeService` the AI
  generator uses (create / update, never a blind write). A stable, namespaced
  `case_key` (`CSV#<hash>`) makes re-importing a corrected CSV **update in place** and
  guarantees CSV keys never collide with the AI generator's endpoint-derived keys —
  the two authoring paths coexist on one project.
- **Partial success, never silent.** A malformed row is reported per-row (1-based) and
  skipped; valid rows still land. A whole-file problem (missing header / required
  column) reports at row 0. Bounded like the document upload: ~1 MB and 500 rows, both
  reported when exceeded, never silently truncated.
- **`edited_by_human=false`.** CSV cases are authored via import, not hand-edited in the
  case editor, so a corrected re-upload updates cleanly rather than forking a protected
  proposal. AI regeneration can't clobber them anyway (distinct `case_key` namespace).

### CSV format

Header row required; column names are case-insensitive (spaces → underscores):

| column            | required | meaning                                             |
| ----------------- | -------- | --------------------------------------------------- |
| `method`          | yes      | GET / POST / PUT / PATCH / DELETE                    |
| `path`            | yes      | endpoint URI, e.g. `api/v1/orders/1`                |
| `expected_status` | yes      | HTTP status to assert (100–599)                     |
| `name`            | no       | short test name (derived from method+path if empty) |
| `payload`         | no       | JSON object body for POST/PUT/PATCH, e.g. `{"qty":2}`|
| `description`     | no       | intent, rendered as an `// Intent:` comment         |
| `authenticated`   | no       | `true` (default) / `false` — act as a factory user  |

## Consequences

- QA gets a precise, reproducible, budget-free authoring path for scenarios they
  already know — complementary to autonomous discovery, not a replacement.
- Imported tests are first-class: they appear in the Tests viewer and run in a normal
  run alongside AI-generated cases, with the honest `spec-grounded` trust mark.
- Authentication renders as `actingAs(User::factory()->create())` — a row marked
  `authenticated` on a target with no `User` factory will ERROR at setup (surfaced as
  ERRORED, not a crash). That is the same factory assumption the AI renderer makes; a
  future iteration could detect factory availability per target for CSV rows too.
- The renderer asserts status (and, for authenticated rows, sets up a user); it does
  not yet assert response body shape from the CSV. A future column (`assert_json`)
  could extend the oracle without changing the persistence model.
