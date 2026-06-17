"""Runner integration (real PHP/Pest) — PestRunner against the bootable fixture.

Marked ``runner``: runs ONLY in the ``runners/laravel`` image via
`make test-runners`, never in the fast backend suite. Feeds representative
hand-written Pest scripts (what a good generation produces around the
deterministic payload/status) to the real PestRunner and asserts the mapped
Result outcomes, evidence capture, and clean teardown.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.execution.pest_runner import PestRunner
from app.execution.types import DbHandle, DbRole, PestScript, TargetEnv
from app.models.enums import Outcome

pytestmark = pytest.mark.runner

APP_PATH = Path(__file__).parent / "fixtures" / "laravel-app"
_GENERATED = APP_PATH / "tests" / "Feature" / "_generated"

# Each script is one Pest feature test with the payload + expected status baked
# in (as the generator would render). name -> (code, expected mapped outcome).
_HAPPY = """<?php
test('store user happy path', function () {
    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $response = $this->postJson('/users', [
        'name' => 'Ada Lovelace',
        'email' => 'ada@example.com',
        'age' => 30,
        'country_id' => $countryId,
        'newsletter' => true,
    ]);
    // CHARACTERIZATION: assert only the success status + that the body is JSON.
    $response->assertStatus(201);
    expect($response->json())->toBeArray();
});
"""

_MISSING_REQUIRED = """<?php
test('missing required name yields 422', function () {
    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $this->postJson('/users', [
        'email' => 'newperson@example.com',
        'age' => 30,
        'country_id' => $countryId,
    ])->assertStatus(422)->assertJsonValidationErrors(['name']);
});
"""

_UNAUTHORIZED = """<?php
test('unauthenticated request yields 401', function () {
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $this->postJson('/users', [
        'name' => 'No Auth',
        'email' => 'noauth@example.com',
        'age' => 30,
        'country_id' => $countryId,
    ])->assertStatus(401);
});
"""

_UNIQUE_DUPLICATE = """<?php
test('duplicate email yields 422', function () {
    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $this->postJson('/users', [
        'name' => 'Duplicate',
        'email' => 'existing@example.com',
        'age' => 30,
        'country_id' => $countryId,
    ])->assertStatus(422)->assertJsonValidationErrors(['email']);
});
"""

# Deliberately wrong expectation → proves FAIL mapping (app returns 422, not 201).
_INTENTIONAL_FAIL = """<?php
test('intentional failure detects a wrong expectation', function () {
    $this->actingAs(\\App\\Models\\User::query()->firstOrFail());
    $countryId = \\App\\Models\\Country::query()->firstOrFail()->id;
    $this->postJson('/users', [
        'name' => 'Bad',
        'email' => 'not-an-email',
        'age' => 30,
        'country_id' => $countryId,
    ])->assertStatus(201);
});
"""

_CASES: dict[str, tuple[str, Outcome]] = {
    "happy": (_HAPPY, Outcome.PASS),
    "missing_required": (_MISSING_REQUIRED, Outcome.PASS),
    "unauthorized": (_UNAUTHORIZED, Outcome.PASS),
    "unique_duplicate": (_UNIQUE_DUPLICATE, Outcome.PASS),
    "intentional_fail": (_INTENTIONAL_FAIL, Outcome.FAIL),
}


def _scripts() -> list[PestScript]:
    return [
        PestScript(uuid.uuid4(), uuid.uuid4(), name, code)
        for name, (code, _) in _CASES.items()
    ]


@pytest.fixture
def target_env() -> Iterator[TargetEnv]:
    evidence = tempfile.mkdtemp(prefix="pest-evidence-")
    yield TargetEnv(
        app_path=str(APP_PATH),
        execution_db=DbHandle("sqlite::memory:", DbRole.WRITABLE_TEST, ephemeral=True),
        evidence_dir=evidence,
    )
    shutil.rmtree(evidence, ignore_errors=True)
    shutil.rmtree(_GENERATED, ignore_errors=True)


def test_pest_runner_produces_correct_outcomes(target_env: TargetEnv) -> None:
    runner = PestRunner()
    scripts = _scripts()
    try:
        results = runner.run(scripts, target_env)
    finally:
        runner.teardown(target_env)

    by_name = {r.name: r for r in results}
    assert set(by_name) == set(_CASES)
    for name, (_code, expected) in _CASES.items():
        assert by_name[name].outcome is expected, (name, by_name[name].message)
        ref = by_name[name].evidence_ref
        assert ref is not None and Path(ref).exists()


def test_teardown_removes_generated_scripts(target_env: TargetEnv) -> None:
    runner = PestRunner()
    runner.run(_scripts(), target_env)
    assert _GENERATED.exists()
    runner.teardown(target_env)
    assert not _GENERATED.exists()
