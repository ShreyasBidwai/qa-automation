"""PHASE 1 — deterministic test plan (no AI).

From an EndpointSpec, derive the set of test cases and their concrete payload
mutations in pure Python. Each case carries its type, payload, expected status,
structural expected shape, oracle_source, and any DB-state dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ingestion.models import EndpointSpec, ValidationField
from app.models.enums import OracleSource, TestType

# A clearly-wrong value per type, used to violate a type/format rule (→ 422).
# Types absent here (string, unknown) have no reliable "wrong type" value.
_INVALID_TYPE_VALUE: dict[str, Any] = {
    "integer": "not-an-integer",
    "numeric": "not-a-number",
    "email": "not-an-email",
    "boolean": "not-a-boolean",
    "array": "not-an-array",
    "uuid": "not-a-uuid",
    "date": "not-a-date",
}

_NUMERIC_TYPES = {"integer", "numeric"}
_NONEXISTENT_ID = 999_999_999


@dataclass(frozen=True)
class ExpectedOutcome:
    status: int
    # Structural only — describes which keys/fields to assert, never values.
    shape: dict[str, Any]


@dataclass(frozen=True)
class DbDependency:
    kind: str  # "row_present" | "row_absent"
    table: str
    column: str | None
    value: Any


@dataclass(frozen=True)
class PlannedCase:
    name: str
    description: str
    case_type: TestType  # HAPPY | NEGATIVE | EDGE
    rule: str  # happy | auth | required | type | min | max | size | exists | unique
    target_field: str | None
    payload: dict[str, Any]
    path_values: dict[str, Any]
    authenticated: bool
    expected: ExpectedOutcome
    oracle_source: OracleSource
    dependencies: list[DbDependency] = field(default_factory=list)


# --- value generators (deterministic) --------------------------------------


def _target_length(constraints: Any) -> int:
    if constraints.size is not None:
        return max(int(constraints.size), 1)
    if constraints.min is not None:
        return max(int(constraints.min), 1)
    if constraints.max is not None:
        return max(min(int(constraints.max), 8), 1)
    return 8


def _valid_value(field_spec: ValidationField) -> Any:
    field_type = field_spec.type
    constraints = field_spec.constraints
    # Relational fields without a declared scalar type are treated as ids.
    if field_spec.relational is not None and field_type == "unknown":
        return 1
    if field_type in _NUMERIC_TYPES:
        if constraints.min is not None:
            return int(constraints.min)
        if constraints.max is not None:
            return min(int(constraints.max), 1)
        return 7
    if field_type == "boolean":
        return True
    if field_type == "email":
        candidate = "user@example.com"
        if constraints.max is not None and len(candidate) > int(constraints.max):
            candidate = "a@b.co"
        return candidate
    if field_type == "date":
        return "2026-01-01"
    if field_type == "uuid":
        return "00000000-0000-0000-0000-000000000000"
    if field_type == "array":
        count = (
            int(constraints.min)
            if constraints.min is not None
            else int(constraints.size) if constraints.size is not None else 1
        )
        return ["item"] * max(count, 1)
    return "a" * _target_length(constraints)


def _below_min(field_spec: ValidationField) -> Any:
    minimum = int(field_spec.constraints.min or 0)
    if field_spec.type in _NUMERIC_TYPES:
        return minimum - 1
    return "a" * max(minimum - 1, 0)


def _above_max(field_spec: ValidationField) -> Any:
    maximum = int(field_spec.constraints.max or 0)
    if field_spec.type in _NUMERIC_TYPES:
        return maximum + 1
    return "a" * (maximum + 1)


def _sized(field_spec: ValidationField, delta: int) -> Any:
    size = int(field_spec.constraints.size or 0) + delta
    if field_spec.type in _NUMERIC_TYPES:
        return size
    return "a" * max(size, 0)


# --- status helpers ---------------------------------------------------------


def _success_status(method: str) -> int:
    upper = method.upper()
    if upper == "POST":
        return 201
    if upper == "DELETE":
        return 204
    return 200


# --- dependency derivation --------------------------------------------------


def _dependencies(
    spec: EndpointSpec,
    payload: dict[str, Any],
    *,
    exists_negative: str | None = None,
    unique_negative: str | None = None,
) -> list[DbDependency]:
    """DB state the case needs to reach exactly the intended outcome.

    A valid `exists` value must reference an existing row; a valid `unique` value
    must be absent. The exists/unique negatives flip their target.
    """
    deps: list[DbDependency] = []
    for field_spec in spec.validation_fields:
        relational = field_spec.relational
        if relational is None or field_spec.name not in payload:
            continue
        value = payload[field_spec.name]
        if field_spec.name == exists_negative:
            deps.append(
                DbDependency("row_absent", relational.table, relational.column, value)
            )
        elif field_spec.name == unique_negative:
            deps.append(
                DbDependency("row_present", relational.table, relational.column, value)
            )
        elif relational.kind == "exists":
            deps.append(
                DbDependency("row_present", relational.table, relational.column, value)
            )
        elif relational.kind == "unique":
            deps.append(
                DbDependency("row_absent", relational.table, relational.column, value)
            )
    return deps


# --- planner ----------------------------------------------------------------


def plan_cases(spec: EndpointSpec) -> list[PlannedCase]:
    fields = spec.validation_fields
    base_payload: dict[str, Any] = {f.name: _valid_value(f) for f in fields}
    path_values: dict[str, Any] = {p: 1 for p in spec.path_params}
    auth = spec.auth_required
    cases: list[PlannedCase] = []

    def negative(
        field_spec: ValidationField,
        rule: str,
        payload: dict[str, Any],
        case_type: TestType,
        *,
        exists_negative: str | None = None,
        unique_negative: str | None = None,
    ) -> PlannedCase:
        return PlannedCase(
            name=f"{field_spec.name}_{rule}",
            description=f"{field_spec.name}: {rule.replace('_', ' ')}",
            case_type=case_type,
            rule=rule.split("_")[0],
            target_field=field_spec.name,
            payload=payload,
            path_values=dict(path_values),
            authenticated=auth,
            expected=ExpectedOutcome(
                status=422, shape={"errors_for": [field_spec.name]}
            ),
            oracle_source=OracleSource.RULE_DERIVED,
            dependencies=_dependencies(
                spec,
                payload,
                exists_negative=exists_negative,
                unique_negative=unique_negative,
            ),
        )

    # 1. Happy path — characterization (status + structural shape only).
    cases.append(
        PlannedCase(
            name="happy",
            description="valid payload satisfying every rule",
            case_type=TestType.HAPPY,
            rule="happy",
            target_field=None,
            payload=dict(base_payload),
            path_values=dict(path_values),
            authenticated=auth,
            expected=ExpectedOutcome(
                status=_success_status(spec.method), shape={"json_object": True}
            ),
            oracle_source=OracleSource.CHARACTERIZATION,
            dependencies=_dependencies(spec, base_payload),
        )
    )

    # 2. Auth — request without authentication (rule-derived).
    if auth:
        cases.append(
            PlannedCase(
                name="auth_unauthenticated",
                description="authenticated endpoint called without auth",
                case_type=TestType.NEGATIVE,
                rule="auth",
                target_field=None,
                payload=dict(base_payload),
                path_values=dict(path_values),
                authenticated=False,
                expected=ExpectedOutcome(status=401, shape={}),
                oracle_source=OracleSource.RULE_DERIVED,
                dependencies=_dependencies(spec, base_payload),
            )
        )

    # 3. One negative/edge per applicable rule, in field then rule order.
    for field_spec in fields:
        if field_spec.required:
            payload = {k: v for k, v in base_payload.items() if k != field_spec.name}
            cases.append(
                negative(field_spec, "required_missing", payload, TestType.NEGATIVE)
            )
        if field_spec.type in _INVALID_TYPE_VALUE:
            payload = dict(base_payload)
            payload[field_spec.name] = _INVALID_TYPE_VALUE[field_spec.type]
            cases.append(
                negative(field_spec, "type_violation", payload, TestType.NEGATIVE)
            )
        if field_spec.constraints.min is not None:
            payload = dict(base_payload)
            payload[field_spec.name] = _below_min(field_spec)
            cases.append(negative(field_spec, "min_boundary", payload, TestType.EDGE))
        if field_spec.constraints.max is not None:
            payload = dict(base_payload)
            payload[field_spec.name] = _above_max(field_spec)
            cases.append(negative(field_spec, "max_boundary", payload, TestType.EDGE))
        if field_spec.constraints.size is not None:
            below = dict(base_payload)
            below[field_spec.name] = _sized(field_spec, -1)
            cases.append(negative(field_spec, "size_below", below, TestType.EDGE))
            above = dict(base_payload)
            above[field_spec.name] = _sized(field_spec, +1)
            cases.append(negative(field_spec, "size_above", above, TestType.EDGE))
        if field_spec.relational and field_spec.relational.kind == "exists":
            payload = dict(base_payload)
            payload[field_spec.name] = _NONEXISTENT_ID
            cases.append(
                negative(
                    field_spec,
                    "exists_missing",
                    payload,
                    TestType.NEGATIVE,
                    exists_negative=field_spec.name,
                )
            )
        if field_spec.relational and field_spec.relational.kind == "unique":
            payload = dict(base_payload)  # valid value, which the dep marks present
            cases.append(
                negative(
                    field_spec,
                    "unique_duplicate",
                    payload,
                    TestType.NEGATIVE,
                    unique_negative=field_spec.name,
                )
            )

    return cases
