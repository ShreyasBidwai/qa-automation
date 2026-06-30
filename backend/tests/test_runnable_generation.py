"""render_script yields a DIRECTLY-RUNNABLE PHPUnit test from messy model output.

The B5→B6 regression guard (ADR-0037): drive ``render_script`` with the
prose-wrapping stub (lead-in prose + ```php fence + "Key decisions" table — what a
real model returns, and exactly what slipped past the clean stub) and prove the
output is a valid, fence-free, prose-free PHP file: a PHPUnit feature-test CLASS
both PHPUnit and Pest run. Also proves the missing-factory fallback: a
factory-dependent case is honestly skipped, not emitted broken.
"""

from __future__ import annotations

from typing import Any

from app.ai.stub import ProseWrappingStubAIProvider, StubAIProvider
from app.generation.plan import plan_cases
from app.generation.render import render_script


def _first_case(endpoint_spec: object) -> Any:
    return plan_cases(endpoint_spec)[0]  # type: ignore[arg-type]


class _CapturingProvider:
    """Records the instruction the renderer sends, returns a minimal valid class."""

    def __init__(self) -> None:
        self.instruction = ""

    def generate(self, prompt: str, context: Any, budget_tokens: int) -> str:
        self.instruction = prompt
        return (
            "<?php\nnamespace Tests\\Feature;\nuse Tests\\TestCase;\n"
            "class X extends TestCase { public function test_x(): void "
            "{ $this->assertTrue(true); } }"
        )

    def triage(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


def test_factories_present_steers_the_model_to_use_them(endpoint_spec: object) -> None:
    # Agnostic: when the target ships factories, generation is told to build setup
    # rows via factories (which encode the real schema) instead of guessing columns.
    spy = _CapturingProvider()
    case = _first_case(endpoint_spec)
    render_script(spy, endpoint_spec, case, 4096, factories_available=True)  # type: ignore[arg-type]
    assert "DEFINES model factories" in spy.instruction
    assert "factory()" in spy.instruction


def test_no_factories_steers_the_model_off_them(endpoint_spec: object) -> None:
    spy = _CapturingProvider()
    case = _first_case(endpoint_spec)
    render_script(spy, endpoint_spec, case, 4096, factories_available=False)  # type: ignore[arg-type]
    assert "NO model factories" in spy.instruction


def test_dependency_order_steer_added_when_case_has_db_dependencies(
    endpoint_spec: object,
) -> None:
    # A case with a foreign-key dependency gets the ordering steer so the model
    # creates dependency rows before the user factory (which would otherwise collide).
    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    dep_case = next(c for c in cases if c.dependencies)
    spy = _CapturingProvider()
    render_script(spy, endpoint_spec, dep_case, 4096, factories_available=True)  # type: ignore[arg-type]
    assert "DB-dependency rows FIRST" in spy.instruction


def test_no_dependency_order_steer_when_case_has_no_dependencies(
    endpoint_spec: object,
) -> None:
    import dataclasses

    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    nodep_case = dataclasses.replace(cases[0], dependencies=[])  # strip deps
    spy = _CapturingProvider()
    render_script(spy, endpoint_spec, nodep_case, 4096, factories_available=True)  # type: ignore[arg-type]
    assert "DB-dependency rows FIRST" not in spy.instruction


def test_render_script_extracts_runnable_php_from_messy_model_output(
    endpoint_spec: object,
) -> None:
    case = _first_case(endpoint_spec)
    out = render_script(ProseWrappingStubAIProvider(), endpoint_spec, case, 4096)  # type: ignore[arg-type]

    assert out.startswith("<?php\n")  # a valid PHP file
    assert out.count("<?php") == 1  # not duplicated
    assert "```" not in out  # markdown fence stripped
    assert "Key decisions" not in out  # trailing table stripped
    assert "Here is the PHPUnit" not in out  # lead-in prose stripped
    # The deterministic provenance header survives, as real PHP comments.
    assert "// Generated test case:" in out
    # It is a PHPUnit class with a uniquely-rewritten name and a test method, and
    # the model's actual assertions are intact. No Pest globals.
    assert "extends TestCase" in out and "Test extends TestCase" in out
    assert "public function test_case_" in out and "assertStatus(422)" in out
    assert "it(" not in out and "uses(" not in out


def test_clean_stub_still_renders_valid_php(endpoint_spec: object) -> None:
    case = _first_case(endpoint_spec)
    out = render_script(StubAIProvider(), endpoint_spec, case, 4096)  # type: ignore[arg-type]
    assert out.startswith("<?php\n")
    assert "// Generated test case:" in out


def test_factory_case_is_skipped_when_no_factories(endpoint_spec: object) -> None:
    case = _first_case(endpoint_spec)
    out = render_script(
        ProseWrappingStubAIProvider(uses_factory=True),
        endpoint_spec,  # type: ignore[arg-type]
        case,
        4096,
        factories_available=False,
    )
    assert "markTestSkipped(" in out  # honestly skipped, not a hard-fail
    assert "deferred" in out  # the reason mentions B10 deferral
    assert out.startswith("<?php\n")


def test_factory_case_runs_when_factories_present(endpoint_spec: object) -> None:
    case = _first_case(endpoint_spec)
    out = render_script(
        ProseWrappingStubAIProvider(uses_factory=True),
        endpoint_spec,  # type: ignore[arg-type]
        case,
        4096,
        factories_available=True,
    )
    assert "markTestSkipped(" not in out  # factories exist → left as the model wrote it
    assert "::factory(" in out
