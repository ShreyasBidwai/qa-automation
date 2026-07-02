"""Oracle honesty — the differentiator. Mandatory and CI-enforced."""

from __future__ import annotations

from app.generation.plan import _echo_fields, plan_cases
from app.ingestion.models import ValidationField
from app.models.enums import OracleSource


def test_happy_is_characterization_and_echoes_safe_fields_only(
    endpoint_spec: object,
) -> None:
    # The users.store fixture is a POST, so a happy characterization additionally
    # asserts the resource echoed the SAFE values we sent — grounded, never invented,
    # and never a server-transformed field (architecture-review DO-NEXT #9).
    happy = next(
        c for c in plan_cases(endpoint_spec) if c.name == "happy"  # type: ignore[arg-type]
    )
    assert happy.oracle_source == OracleSource.CHARACTERIZATION
    assert happy.expected.shape["json_object"] is True
    echo = happy.expected.shape.get("echo", {})
    assert "name" in echo and "age" in echo  # safe scalars a create echoes back
    assert "email" not in echo  # normalised/transformed → never echo-asserted
    assert "errors_for" not in happy.expected.shape


def test_echo_fields_excludes_sensitive_and_non_create() -> None:
    fields = [
        ValidationField(name="name", raw_rules=["required", "string"], required=True, type="string"),
        ValidationField(name="password", raw_rules=["required"], required=True, type="string"),
        ValidationField(name="email", raw_rules=["required", "email"], required=True, type="email"),
        ValidationField(name="age", raw_rules=["required"], required=True, type="integer"),
        ValidationField(name="nickname", raw_rules=[], required=False, type="string"),
    ]
    payload = {"name": "x", "password": "y", "email": "z@e", "age": 21, "nickname": "n"}
    echo = _echo_fields("POST", fields, payload)
    # password (secret name), email (type+name+rule), nickname (optional) excluded.
    assert echo == {"name": "x", "age": 21}
    # A read never echoes submitted values.
    assert _echo_fields("GET", fields, payload) == {}


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
