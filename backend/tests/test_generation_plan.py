"""PHASE 1 plan derivation — exact case set, payloads, statuses, oracle (offline)."""

from __future__ import annotations

from app.generation.plan import PlannedCase, plan_cases
from app.models.enums import OracleSource, TestType

EXPECTED_CASES = [
    "happy",
    "auth_unauthenticated",
    "name_required_missing",
    "name_max_boundary",
    "email_required_missing",
    "email_type_violation",
    "email_unique_duplicate",
    "age_required_missing",
    "age_type_violation",
    "age_min_boundary",
    "age_max_boundary",
    "country_id_required_missing",
    "country_id_exists_missing",
    "newsletter_type_violation",
]


def _by_name(cases: list[PlannedCase]) -> dict[str, PlannedCase]:
    return {case.name: case for case in cases}


def test_plans_exactly_the_expected_case_set(endpoint_spec: object) -> None:
    cases = plan_cases(endpoint_spec)  # type: ignore[arg-type]
    assert [case.name for case in cases] == EXPECTED_CASES


def test_happy_case_is_valid_payload_with_success_status(endpoint_spec: object) -> None:
    happy = _by_name(plan_cases(endpoint_spec))["happy"]  # type: ignore[arg-type]
    assert happy.case_type == TestType.HAPPY
    assert happy.oracle_source == OracleSource.CHARACTERIZATION
    assert happy.expected.status == 201  # POST → 201
    assert happy.authenticated is True
    assert set(happy.payload) == {"name", "email", "age", "country_id", "newsletter"}
    assert happy.payload["age"] == 18
    assert happy.payload["email"] == "user@example.com"
    deps = {(d.kind, d.table, d.column) for d in happy.dependencies}
    assert ("row_present", "countries", "id") in deps  # exists ref must exist
    assert ("row_absent", "users", "email") in deps  # unique value must not pre-exist


def test_auth_case(endpoint_spec: object) -> None:
    case = _by_name(plan_cases(endpoint_spec))["auth_unauthenticated"]  # type: ignore[arg-type]
    assert case.case_type == TestType.NEGATIVE
    assert case.rule == "auth"
    assert case.oracle_source == OracleSource.RULE_DERIVED
    assert case.expected.status == 401
    assert case.authenticated is False


def test_required_missing_omits_the_field(endpoint_spec: object) -> None:
    case = _by_name(plan_cases(endpoint_spec))["age_required_missing"]  # type: ignore[arg-type]
    assert "age" not in case.payload
    assert case.case_type == TestType.NEGATIVE
    assert case.expected.status == 422
    assert case.expected.shape == {"errors_for": ["age"]}
    assert case.oracle_source == OracleSource.RULE_DERIVED


def test_type_violation_uses_wrong_typed_value(endpoint_spec: object) -> None:
    cases = _by_name(plan_cases(endpoint_spec))  # type: ignore[arg-type]
    assert cases["age_type_violation"].payload["age"] == "not-an-integer"
    assert cases["email_type_violation"].payload["email"] == "not-an-email"
    assert cases["newsletter_type_violation"].payload["newsletter"] == "not-a-boolean"
    assert cases["age_type_violation"].expected.status == 422


def test_boundary_edges(endpoint_spec: object) -> None:
    cases = _by_name(plan_cases(endpoint_spec))  # type: ignore[arg-type]
    low = cases["age_min_boundary"]
    high = cases["age_max_boundary"]
    assert low.case_type == TestType.EDGE and low.payload["age"] == 17
    assert high.case_type == TestType.EDGE and high.payload["age"] == 121
    assert low.expected.status == 422 and high.expected.status == 422
    name_max = cases["name_max_boundary"]
    assert name_max.case_type == TestType.EDGE
    assert len(name_max.payload["name"]) == 256  # above max length (255)


def test_exists_negative_references_absent_id(endpoint_spec: object) -> None:
    case = _by_name(plan_cases(endpoint_spec))["country_id_exists_missing"]  # type: ignore[arg-type]
    assert case.payload["country_id"] == 999_999_999
    assert case.expected.status == 422
    assert case.oracle_source == OracleSource.RULE_DERIVED
    deps = {(d.kind, d.table, d.column, d.value) for d in case.dependencies}
    assert ("row_absent", "countries", "id", 999_999_999) in deps


def test_unique_negative_marks_existing_row_dependency(endpoint_spec: object) -> None:
    case = _by_name(plan_cases(endpoint_spec))["email_unique_duplicate"]  # type: ignore[arg-type]
    assert case.payload["email"] == "user@example.com"
    assert case.expected.status == 422
    deps = {(d.kind, d.table, d.column, d.value) for d in case.dependencies}
    assert ("row_present", "users", "email", "user@example.com") in deps
