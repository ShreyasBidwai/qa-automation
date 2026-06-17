# Sprint 1 gate — the thesis gate (manual AAHOA procedure)

> Sprint 1 exists to answer the riskiest question: **are the generated tests good
> enough to keep?** This is the *manual* half of that gate — running the
> walking skeleton against one **real AAHOA endpoint** with the real AI provider
> and judging keep-worthiness. The *automated* half (compile + run + mutant-kill)
> is enforced in CI by `make test` (fast) and `make test-runners`
> (`backend/tests/test_mutant_kill_gate.py`).
>
> **If this gate fails, stop and fix generation before Sprint 2 — this is the
> whole point** (project plan, Sprint 1 DoD).

## Prerequisites

1. **A local checkout of the AAHOA Laravel repo** with `composer install` run,
   plus the PHP-helper dependency the extractor needs:
   ```bash
   composer require nikic/php-parser   # in the AAHOA repo
   php artisan route:list --json       # sanity-check the route you'll target
   ```
2. **A real AI provider** (NOT the StubAIProvider): the `claude_cli` provider
   (`claude -p`) or the configured Gemini provider, with credentials available
   in the environment. See `backend/app/ai/` and `build_ai_provider`.
3. **A runner environment** that can boot the target app + a throwaway test DB —
   the `runners/laravel` image (PHP 8.2 + Composer + Pest), or an equivalent
   local PHP/Pest setup pointed at an ephemeral sqlite/Postgres DB.
4. Pick **one** authenticated, validated write endpoint (e.g. a `store` action
   with a FormRequest), mirroring the fixture's `users.store`.

## Procedure

Drive the assembled skeleton (`app/reporting/orchestrator.py::run_walking_skeleton`)
against the chosen endpoint, wired to the **real** collaborators:

- `extractor` = `LaravelExtractor()` (real `php artisan` + `extract_validation.php`),
- `generator` = `TestGenerator(provider=build_ai_provider(settings), budget_tokens=…, generated_by="claude-cli")`,
- `runner`    = `PestRunner()` against the AAHOA app,
- `target_env`= the writable, ephemeral test DB only (dual-DB rule, Architecture §9).

It will: extract the endpoint → generate cases + Pest scripts → execute them →
return the 10-line `RunReport` and persist a coverage row. Capture the rendered
report and the generated scripts for review.

```
# sketch — fill in project_id / route target / DB handle for your environment
report = await run_walking_skeleton(
    session=session, project_id=project_id,
    repo_path="/path/to/aahoa", route_target=RouteTarget(name="<route.name>"),
    extractor=LaravelExtractor(), generator=generator,
    runner=PestRunner(), target_env=target_env,
)
print(report.render())
```

## Keep-worthiness checklist

Review the generated scripts + the report against each criterion:

- [ ] **Compile** — every generated Pest script is syntactically valid and the
      suite loads (no parse/boot errors).
- [ ] **Run** — the suite executes against the booted app + test DB; results map
      to pass/fail/error (no silent skips).
- [ ] **Assert meaningfully** — negatives/edges are `rule-derived` and assert the
      exact status + the targeted field error; the happy case is
      `characterization` (asserts success status + JSON shape only, never invented
      body values). No tautologies.
- [ ] **Mutant-kill** — seed at least one deliberate bug in the endpoint (drop a
      `required`/`min` rule) and confirm the guarding negative test FAILS. (CI
      enforces two mutations automatically; do one by hand here on the real
      endpoint as a spot check.)
- [ ] **Oracle honesty** — the report's breakdown is accurate: N rule-derived
      (strong), M characterization (weak — needs specs), **0 spec-grounded**.
- [ ] **Would a senior dev keep these?** — would an experienced QA engineer keep
      these tests (possibly with minor edits) rather than delete and rewrite?

## Verdict

_Fill in after running against a real AAHOA endpoint._

- **Endpoint tested:** _<method + route name>_
- **Date / reviewer:** _<…>_
- **Generated / kept (no edit):** _<n> / <m>_
- **Mutant-kill spot check:** _pass / fail — <which rule was dropped, did the guard fail?>_
- **Keep-worthy (senior-dev judgment):** _yes / no_
- **Verdict:** _PASS / FAIL_
- **If FAIL — what to fix in generation before Sprint 2:** _<…>_
