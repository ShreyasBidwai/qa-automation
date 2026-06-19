# ADR-0022: Severity scoring — blast radius × failure shape

- Status: Accepted
- Date: 2026-06-19
- Deciders: Engineering

## Context

T7.2 groups failures into Findings, each carrying a **confidence** (the strongest
oracle tier in its group, ADR-0021). A report still needs to answer "which bug do
I fix first?". That is two questions, and conflating them is a mistake:

- **Severity** — how bad is this bug? A property of the bug.
- **Confidence** — how sure are we it *is* a bug? A property of our evidence.

A high-blast, high-confidence bug must sort to the top; a low-confidence
"behaviour changed" on an isolated node must sink. T7.3 fills the `severity`
placeholder and produces the triage ranking. It must be **deterministic** (no AI,
no clustering), derived from data already reachable from a Finding plus the Brain,
and add **no migration** (the existing `findings.severity` string column holds the
scored value).

"What is critical vs minor?" is a real product decision, so the thresholds are
fixed here.

## Decision

**Severity vocabulary** (`Severity` enum, stored as its string in the existing
column): `critical | major | minor`. `unset` remains the pre-scored default.

**Two inputs:**

1. **Blast radius** — `CrossLayerResolver.impact` on the finding's anchor node
   (the representative failing test's `target_node`, the entry node of the failing
   journey — the node reachable from a persisted Finding without a new column).
   `blast = |callers| + |writes| + |roles|` — the count of dependent
   pages/endpoints, written tables, and gating roles. A node many things depend on
   is a wide blast.

2. **Failure shape** — from the representative result's `outcome` and the group's
   `oracle_source`, into three classes:
   - **hard** = `error` outcome (a crash / 5xx-class failure),
   - **rule** = `fail` with a `rule-derived` or `spec-grounded` oracle (a real
     rule/spec was violated),
   - **soft** = `fail` with a `characterization` oracle (behaviour merely changed;
     may be fine).

   `hard` and `rule` both "weigh heavy"; `soft` is light.

**Thresholds** (`WIDE_BLAST_THRESHOLD = 3`):

| failure shape \ blast | isolated/local (`< 3`) | wide (`>= 3`) |
|-----------------------|------------------------|---------------|
| **hard** / **rule**   | major                  | **critical**  |
| **soft**              | minor                  | major         |

Equivalently: `critical` iff (hard|rule) **and** wide; `minor` iff soft **and**
not wide; `major` otherwise. So a 5xx/error always outranks a soft mismatch at the
same blast (major>minor when not wide, critical>major when wide), and a wide,
rule-derived bug is critical while an isolated characterization mismatch is minor.

**Ranking** (computed on read — no stored score). A finding's deterministic sort
key is `(severity desc, confidence desc, root_cause_key asc)`:

- `severity` ranked `critical(3) > major(2) > minor(1) > unset(0)`,
- `confidence` ranked `spec-grounded(3) > rule-derived(2) > characterization(1)`
  (the same tier order as ADR-0021),
- `root_cause_key` as a stable, content-derived final tie-break.

Severity × confidence: a critical rule-derived finding sorts above a major
characterization one, and equal sev+confidence ties resolve identically every run.

## Consequences

**Easier**
- Triage is honest: severity (how bad) and confidence (how sure) are scored
  separately and combined only at ranking time. The two never contaminate.
- Fully deterministic and explainable from the thresholds; no migration — the
  `findings.severity` string column from ADR-0020 suffices, ranking is read-time.

**Harder / watch-outs**
- The anchor for blast is the test's `target_node`, not the deepest journey node
  (which would need persisting the anchor id). For a UI test this measures the
  page's blast, not the underlying table's; a future refinement can store the
  deepest anchor and re-anchor without changing the scoring rule.
- `WIDE_BLAST_THRESHOLD = 3` and the hard/rule equivalence are deliberately coarse
  product calls; they are tunable here by ADR, not scattered magic numbers.
- A missing/None target node, or an impact lookup that fails, degrades to blast 0
  (severity still scored from the failure shape) — never an error.
