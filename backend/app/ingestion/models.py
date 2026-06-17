"""Normalized ingestion output types (the input contract for T1.4 generation).

`EndpointSpec` maps downstream to test_cases.target_node / steps / expected. The
`ValidationField` shape captures enough to derive every negative/edge case the
generator needs: required→missing-field, type→wrong-type, email→invalid-format,
min/max→boundary, exists→not-found, unique→duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldConstraints:
    min: float | None = None
    max: float | None = None
    size: float | None = None


@dataclass(frozen=True)
class RelationalRule:
    kind: str  # "exists" | "unique"
    table: str
    column: str | None = None


@dataclass(frozen=True)
class ValidationField:
    name: str
    raw_rules: list[str]
    required: bool
    # string | integer | numeric | email | boolean | array | date | uuid | unknown
    type: str
    constraints: FieldConstraints = field(default_factory=FieldConstraints)
    relational: RelationalRule | None = None


@dataclass(frozen=True)
class EndpointSpec:
    method: str
    uri: str
    route_name: str | None
    auth_required: bool
    path_params: list[str] = field(default_factory=list)
    query_params: list[str] = field(default_factory=list)
    validation_fields: list[ValidationField] = field(default_factory=list)
