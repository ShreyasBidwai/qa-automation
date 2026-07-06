"""PHASE 1 plan derivation — exact case set, payloads, statuses, oracle (offline)."""

from __future__ import annotations

from dataclasses import replace

from app.generation.plan import PlannedCase, ResponseExpectation, plan_cases
from app.ingestion.models import (
    EndpointSpec,
    FieldConstraints,
    ValidationField,
)
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
    # An api route with no bound path params asserts a 2xx BAND, not a hardcoded code
    # (ADR-0063); 201 is only the representative hint for POST.
    assert happy.expected.expectation == ResponseExpectation.SUCCESS_JSON
    assert happy.expected.status == 201  # POST → 201 (representative)
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


# --- route-class awareness (ADR-0063) ---------------------------------------
#
# A web route (login/OAuth/form: session + redirects, NOT JSON) must assert
# DIFFERENTLY from an api route on the same events, or every case false-fails —
# the login-module regression that motivated ADR-0063.


def _web_login_post() -> EndpointSpec:
    """A web (non-api) auth-guarded form POST — e.g. submitting login credentials."""
    return EndpointSpec(
        method="POST",
        uri="login",
        route_name="login.store",
        auth_required=True,
        path_params=[],
        query_params=[],
        validation_fields=[
            ValidationField(
                name="email",
                raw_rules=["required", "email"],
                required=True,
                type="email",
                constraints=FieldConstraints(),
            ),
        ],
        is_api=False,
    )


def test_web_happy_asserts_success_or_redirect_not_json() -> None:
    happy = _by_name(plan_cases(_web_login_post()))["happy"]
    # A web happy path may 200 (view) OR 302 (redirect) — never a JSON body.
    assert happy.expected.expectation == ResponseExpectation.SUCCESS_OR_REDIRECT
    assert happy.expected.shape == {}  # no JSON structure/echo on a web route


def test_web_auth_unauthenticated_expects_a_redirect_not_401() -> None:
    case = _by_name(plan_cases(_web_login_post()))["auth_unauthenticated"]
    # Laravel's auth middleware redirects a web request to /login (302), not 401.
    assert case.expected.expectation == ResponseExpectation.REDIRECT
    assert case.expected.status == 302
    assert case.oracle_source == OracleSource.RULE_DERIVED


def test_web_validation_negative_expects_session_errors_not_422() -> None:
    case = _by_name(plan_cases(_web_login_post()))["email_required_missing"]
    # A web validation failure redirects back with SESSION errors, not a 422 JSON body.
    assert case.expected.expectation == ResponseExpectation.REDIRECT_WITH_ERRORS
    assert case.expected.status == 302
    assert case.expected.shape == {"errors_for": ["email"]}


def test_api_auth_unauthenticated_still_expects_401() -> None:
    # The api route class is unchanged: 401, exact status (no regression).
    case = _by_name(plan_cases(_web_login_post_as_api()))["auth_unauthenticated"]
    assert case.expected.expectation == ResponseExpectation.STATUS
    assert case.expected.status == 401


def _web_login_post_as_api() -> EndpointSpec:
    return replace(_web_login_post(), uri="api/login", is_api=True)


def test_happy_with_bound_path_params_only_asserts_reachable() -> None:
    # A GET /resource/{id} happy path can't be asserted as 2xx statically — the record
    # may not be seeded (route-model-binding 404 is expected), so pin "no server error".
    spec = EndpointSpec(
        method="GET",
        uri="login/enter_password/{encId}",
        route_name="login.enter_password",
        auth_required=False,
        path_params=["encId"],
        query_params=[],
        validation_fields=[],
        is_api=False,
    )
    happy = _by_name(plan_cases(spec))["happy"]
    assert happy.expected.expectation == ResponseExpectation.REACHABLE
    assert happy.expected.shape == {}
    assert happy.path_values == {"encId": 1}
