"""Normalize raw Laravel validation rules into typed ValidationFields.

Deterministic and AI-free. Input is the rule spec per field as the PHP AST
helper emits it: a pipe-string ("required|email|max:255") or a list of tokens
(["required", "email", "max:255"]).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.ingestion.models import FieldConstraints, RelationalRule, ValidationField

# Most specific type wins (email implies string but is more useful downstream).
_TYPE_PRIORITY = (
    "email",
    "uuid",
    "integer",
    "numeric",
    "boolean",
    "array",
    "date",
    "string",
)
_RELATIONAL_KINDS = ("exists", "unique")


def _tokens(rule_spec: str | list[str]) -> list[str]:
    if isinstance(rule_spec, str):
        return [tok.strip() for tok in rule_spec.split("|") if tok.strip()]
    return [str(tok).strip() for tok in rule_spec if str(tok).strip()]


def _split(token: str) -> tuple[str, list[str]]:
    head, sep, rest = token.partition(":")
    if not sep:
        return head, []
    return head, [arg.strip() for arg in rest.split(",")]


def _as_number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def normalize_field(name: str, rule_spec: str | list[str]) -> ValidationField:
    tokens = _tokens(rule_spec)
    parsed = [_split(tok) for tok in tokens]
    names = {head for head, _ in parsed}

    required = "required" in names
    field_type = next((t for t in _TYPE_PRIORITY if t in names), "unknown")

    min_value: float | None = None
    max_value: float | None = None
    size_value: float | None = None
    relational: RelationalRule | None = None

    for head, args in parsed:
        if head == "min" and args:
            min_value = _as_number(args[0])
        elif head == "max" and args:
            max_value = _as_number(args[0])
        elif head == "size" and args:
            size_value = _as_number(args[0])
        elif head in _RELATIONAL_KINDS and relational is None and args:
            relational = RelationalRule(
                kind=head,
                table=args[0],
                column=args[1] if len(args) > 1 else None,
            )

    return ValidationField(
        name=name,
        raw_rules=tokens,
        required=required,
        type=field_type,
        constraints=FieldConstraints(min=min_value, max=max_value, size=size_value),
        relational=relational,
    )


def normalize_rules(
    rules: Mapping[str, str | list[str]],
) -> list[ValidationField]:
    return [normalize_field(name, spec) for name, spec in rules.items()]
