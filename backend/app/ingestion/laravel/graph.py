"""Parse the extract_graph.php JSON into typed, whole-repo Brain facts.

Deterministic and AI-free: the PHP helper (php/extract_graph.php) uses
nikic/php-parser to emit models, migrations, and controller actions; this module
only invokes it (through the injectable runner) and parses its JSON — never the
PHP source itself. Mirrors validation.py (T1.3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ingestion.commands import CommandRunner, check_output
from app.ingestion.errors import GraphExtractionError


@dataclass(frozen=True)
class Relationship:
    name: str
    kind: str  # belongsTo | hasMany | hasOne | belongsToMany | ...
    related: str  # related model FQCN


@dataclass(frozen=True)
class ModelMeta:
    cls: str  # FQCN, e.g. App\Models\User
    table: str  # explicit $table or convention-derived
    fillable: list[str]
    relationships: list[Relationship]


@dataclass(frozen=True)
class MigrationMeta:
    table: str
    columns: list[str]


@dataclass(frozen=True)
class ActionValidation:
    source: str  # form_request | inline_validate | none
    fields: list[str]
    # Rule SPECS keyed by field (e.g. {"age": "required|integer|min:18"}); pipe-string
    # rules only (the common FormRequest form). Lets generation infer TYPES so it emits
    # type-correct payloads instead of a generic placeholder — for ANY project.
    rules: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionMeta:
    controller: str  # controller FQCN
    action: str  # method name
    model_refs: list[str]  # statically-referenced model FQCNs
    validation: ActionValidation


@dataclass(frozen=True)
class RepoGraph:
    models: list[ModelMeta]
    migrations: list[MigrationMeta]
    actions: list[ActionMeta]


def _obj_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = data.get(key, [])
    if not isinstance(raw, list):
        raise GraphExtractionError(f"graph helper '{key}' is not an array")
    return [item for item in raw if isinstance(item, dict)]


def _str_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _relationship(data: dict[str, Any]) -> Relationship:
    return Relationship(
        name=str(data.get("name", "")),
        kind=str(data.get("kind", "")),
        related=str(data.get("related", "")),
    )


def _model(data: dict[str, Any]) -> ModelMeta:
    rels = data.get("relationships", [])
    relationships = (
        [_relationship(r) for r in rels if isinstance(r, dict)]
        if isinstance(rels, list)
        else []
    )
    return ModelMeta(
        cls=str(data.get("class", "")),
        table=str(data.get("table", "")),
        fillable=_str_list(data.get("fillable")),
        relationships=relationships,
    )


def _migration(data: dict[str, Any]) -> MigrationMeta:
    return MigrationMeta(
        table=str(data.get("table", "")),
        columns=_str_list(data.get("columns")),
    )


def _action(data: dict[str, Any]) -> ActionMeta:
    validation = data.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}
    return ActionMeta(
        controller=str(data.get("controller", "")),
        action=str(data.get("action", "")),
        model_refs=_str_list(data.get("model_refs")),
        validation=ActionValidation(
            source=str(validation.get("source", "none")),
            fields=_str_list(validation.get("fields")),
        ),
    )


def parse_graph_output(stdout: str) -> RepoGraph:
    try:
        data: Any = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GraphExtractionError("graph helper did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise GraphExtractionError("graph helper output is not an object")
    return RepoGraph(
        models=[_model(m) for m in _obj_list(data, "models")],
        migrations=[_migration(m) for m in _obj_list(data, "migrations")],
        actions=[_action(a) for a in _obj_list(data, "actions")],
    )


def extract_graph(
    *,
    repo_path: str,
    runner: CommandRunner,
    php_path: str,
    helper_script: str,
    timeout: float,
) -> RepoGraph:
    result = runner([php_path, helper_script, repo_path], None, timeout)
    stdout = check_output(result, what="php graph helper")
    return parse_graph_output(stdout)
