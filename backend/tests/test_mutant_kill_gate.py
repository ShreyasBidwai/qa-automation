"""Mutant-kill gate (the Sprint 1 thesis experiment) — runs in the runner image.

Marked ``runner``: seeds a deliberate bug into a COPY of the fixture app (drops a
validation rule), runs the rule-derived negative test that guards that rule, and
asserts the test now FAILS — i.e., the generated oracle catches the regression
(it "kills the mutant"). A test that does NOT fail on its mutation is a tautology
and is surfaced as a gate failure. The fixture is never mutated; the copy is torn
down on completion and failure (Standards §11).
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.execution.php_test_runner import PhpTestRunner
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv
from app.models.enums import Outcome

pytestmark = pytest.mark.runner

FIXTURE = Path(__file__).parent / "fixtures" / "laravel-app"
_REQUEST = "app/Http/Requests/StoreUserRequest.php"

# Rule-derived negative tests that guard a specific rule. On the correct app each
# PASSES (the app returns 422); after the guarded rule is dropped, the app stops
# returning 422 and the test must FAIL.
_GUARD_EMAIL_REQUIRED = """<?php
test('email required missing yields 422', function () {
    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $this->postJson('/users', [
        'name' => 'NoEmail', 'age' => 30, 'country_id' => $countryId,
    ])->assertStatus(422)->assertJsonValidationErrors(['email']);
});
"""

_GUARD_AGE_MIN = """<?php
test('age below minimum yields 422', function () {
    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $this->postJson('/users', [
        'name' => 'Young', 'email' => 'young@example.com',
        'age' => 17, 'country_id' => $countryId,
    ])->assertStatus(422)->assertJsonValidationErrors(['age']);
});
"""

# A tautological "guard" that passes regardless of the app's behaviour — it can
# never kill a mutant, so the gate must classify it as a failure.
_TAUTOLOGY = """<?php
test('tautological assertion', function () {
    expect(true)->toBeTrue();
});
"""


@dataclass(frozen=True)
class Mutation:
    name: str
    find: str
    replace: str


_DROP_REQUIRED_EMAIL = Mutation(
    "drop_required_email",
    "'email' => 'required|email|unique:users,email'",
    "'email' => 'email|unique:users,email'",
)
_DROP_MIN_AGE = Mutation(
    "drop_min_age",
    "'age' => 'required|integer|min:18|max:120'",
    "'age' => 'required|integer|max:120'",
)


def _env(app_path: str, evidence_dir: str) -> TargetEnv:
    return TargetEnv(
        app_path=app_path,
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=evidence_dir,
    )


def _run_guard(app_path: str, name: str, code: str) -> Outcome:
    """Run a single guard test against the app at app_path; clean up after."""
    runner = PhpTestRunner()
    evidence = tempfile.mkdtemp(prefix="gate-evidence-")
    env = _env(app_path, evidence)
    script = PestScript(uuid.uuid4(), uuid.uuid4(), name, code)
    try:
        results = runner.run([script], env)
        return results[0].outcome
    finally:
        runner.teardown(env)
        shutil.rmtree(evidence, ignore_errors=True)


def _run_guard_on_mutant(mutation: Mutation, name: str, code: str) -> Outcome:
    """Apply the mutation to a COPY of the fixture, run the guard, tear it down."""
    workdir = tempfile.mkdtemp(prefix="gate-mutant-")
    app_copy = Path(workdir) / "app"
    try:
        shutil.copytree(FIXTURE, app_copy)
        request = app_copy / _REQUEST
        original = request.read_text(encoding="utf-8")
        assert mutation.find in original, f"mutation target not found: {mutation.name}"
        request.write_text(
            original.replace(mutation.find, mutation.replace, 1), encoding="utf-8"
        )
        return _run_guard(str(app_copy), name, code)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@dataclass(frozen=True)
class GateVerdict:
    mutation: str
    passed_clean: bool
    failed_on_mutant: bool

    @property
    def killed(self) -> bool:
        # A mutant is killed only if the guard is meaningful (passes on correct
        # code) AND catches the regression (fails on the mutant).
        return self.passed_clean and self.failed_on_mutant


def _assess(mutation: Mutation, guard_name: str, guard_code: str) -> GateVerdict:
    clean = _run_guard(str(FIXTURE), guard_name, guard_code)
    mutant = _run_guard_on_mutant(mutation, guard_name, guard_code)
    return GateVerdict(
        mutation=mutation.name,
        passed_clean=clean is Outcome.PASS,
        failed_on_mutant=mutant is Outcome.FAIL,
    )


def test_mutations_are_killed_by_their_guarding_tests() -> None:
    verdicts = [
        _assess(_DROP_REQUIRED_EMAIL, "email_required_missing", _GUARD_EMAIL_REQUIRED),
        _assess(_DROP_MIN_AGE, "age_min_boundary", _GUARD_AGE_MIN),
    ]
    for verdict in verdicts:
        assert verdict.passed_clean, f"{verdict.mutation}: guard must pass on clean app"
        assert verdict.failed_on_mutant, (
            f"{verdict.mutation}: guard did not fail on the mutant — tautological "
            "oracle, gate FAILS"
        )
        assert verdict.killed


def test_tautological_guard_does_not_kill_and_fails_the_gate() -> None:
    # Pair a real mutation with a tautological guard: it passes even on the
    # mutant, so it kills nothing — exactly what the gate must reject.
    verdict = _assess(_DROP_MIN_AGE, "tautology", _TAUTOLOGY)
    assert verdict.failed_on_mutant is False
    assert verdict.killed is False
