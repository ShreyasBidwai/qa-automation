"""Oracle honesty — the differentiator. Mandatory and CI-enforced."""

from __future__ import annotations

from app.generation.plan import plan_cases
from app.models.enums import OracleSource


def test_happy_is_characterization_and_structural_only(endpoint_spec: object) -> None:
    happy = next(
        c for c in plan_cases(endpoint_spec) if c.name == "happy"  # type: ignore[arg-type]
    )
    assert happy.oracle_source == OracleSource.CHARACTERIZATION
    # Structural shape only — asserts the body is JSON, never specific values.
    assert happy.expected.shape == {"json_object": True}
    assert "errors_for" not in happy.expected.shape


def test_negatives_and_edges_are_rule_derived(endpoint_spec: object) -> None:
    for case in plan_cases(endpoint_spec):  # type: ignore[arg-type]
        if case.name == "happy":
            assert case.oracle_source == OracleSource.CHARACTERIZATION
        else:
            assert case.oracle_source == OracleSource.RULE_DERIVED


def test_nothing_is_spec_grounded(endpoint_spec: object) -> None:
    # No requirements ingested this sprint — spec-grounded is forbidden.
    assert all(
        c.oracle_source != OracleSource.SPEC_GROUNDED
        for c in plan_cases(endpoint_spec)  # type: ignore[arg-type]
    )
