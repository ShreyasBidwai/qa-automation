"""Rebuild the generator's ``EndpointSpec`` from a Brain endpoint node.

The inverse of ingestion: the Laravel ingester stores an endpoint's method/uri/auth
+ captured validation spec on the node's ``attributes``; this reconstructs the
``EndpointSpec`` the deterministic planner needs, so generation runs off the Brain
without re-reading the repo. Pure (node → spec), no I/O.

Lives here (not in ``app.api``) so both the run executor (``app.api.real_execution``)
and NL-authoring (``app.modes.mode_c_api``) can reuse it without an api⇄modes import
cycle. ``real_execution`` re-exports these names for backward compatibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ingestion.laravel.normalize import normalize_rules
from app.ingestion.laravel.route_list import path_params_from_uri
from app.ingestion.models import (
    EndpointSpec,
    FieldConstraints,
    RelationalRule,
    ValidationField,
)
from app.models.model_node import ModelNode


def _validation_field(data: dict[str, Any] | str) -> ValidationField:
    # The static whole-repo Laravel ingester records validation fields as bare
    # names (``list[str]``); the per-endpoint extractor records rich dicts. Accept
    # both so generation works off a statically-ingested Brain (the default path).
    if isinstance(data, str):
        data = {"name": data}
    constraints = data.get("constraints") or {}
    relational = data.get("relational")
    return ValidationField(
        name=str(data.get("name", "")),
        raw_rules=list(data.get("raw_rules", [])),
        required=bool(data.get("required", False)),
        type=str(data.get("type", "unknown")),
        constraints=FieldConstraints(
            min=constraints.get("min"),
            max=constraints.get("max"),
            size=constraints.get("size"),
        ),
        relational=(
            RelationalRule(
                kind=relational["kind"],
                table=relational["table"],
                column=relational.get("column"),
            )
            if relational
            else None
        ),
    )


def endpoint_spec_from_node(node: ModelNode) -> EndpointSpec:
    """Rebuild the generator's ``EndpointSpec`` from an endpoint node's attributes.

    The Laravel ingestor stores method/uri/auth + the captured validation spec on
    the node (``ingester.py``); this is its inverse so the backend generator can run
    off the Brain without re-reading the repo.
    """
    attrs = node.attributes or {}
    uri = str(attrs.get("uri", ""))
    validation = attrs.get("validation") or {}
    return EndpointSpec(
        method=str(attrs.get("method", "GET")),
        uri=uri,
        route_name=attrs.get("name"),
        auth_required=bool(attrs.get("auth_required", False)),
        path_params=path_params_from_uri(uri),
        query_params=[],
        validation_fields=_validation_fields_from(validation),
    )


def _validation_fields_from(validation: Mapping[str, Any]) -> list[ValidationField]:
    """Typed validation fields from a node's ``validation`` attribute.

    Prefer the captured rule SPECS (``rules`` map → ``normalize_rules``) so each field
    carries its TYPE/constraints and the plan emits type-correct payloads. Fall back to
    bare field names (``fields``) when only names were captured — older Brains, or
    array-form / ``Rule::*`` rules the static parser can't reduce to a pipe string.
    """
    rules = validation.get("rules")
    if isinstance(rules, Mapping) and rules:
        return list(normalize_rules(rules))
    return [_validation_field(f) for f in validation.get("fields", [])]
