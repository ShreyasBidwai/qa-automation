"""Rule normalization correctness — the contract T1.4 generation depends on."""

from __future__ import annotations

from app.ingestion.laravel.normalize import normalize_field, normalize_rules


def test_required_email_unique_maps_format_and_relational() -> None:
    field = normalize_field("email", "required|email|unique:users,email")
    assert field.required is True
    assert field.type == "email"  # → invalid-format tests
    assert field.relational is not None
    assert field.relational.kind == "unique"  # → duplicate tests
    assert field.relational.table == "users"
    assert field.relational.column == "email"
    assert field.raw_rules == ["required", "email", "unique:users,email"]


def test_integer_with_min_and_max_constraints() -> None:
    field = normalize_field("age", "required|integer|min:18|max:120")
    assert field.type == "integer"  # → wrong-type tests
    assert field.required is True  # → missing-field tests
    assert field.constraints.min == 18.0  # → boundary tests
    assert field.constraints.max == 120.0


def test_exists_relational_with_unknown_type() -> None:
    field = normalize_field("country_id", "required|exists:countries,id")
    assert field.relational is not None
    assert field.relational.kind == "exists"  # → not-found tests
    assert field.relational.table == "countries"
    assert field.relational.column == "id"
    assert field.type == "unknown"  # no explicit type rule


def test_nullable_field_is_not_required() -> None:
    field = normalize_field("age", "nullable|integer|min:18")
    assert field.required is False
    assert field.type == "integer"
    assert field.constraints.min == 18.0


def test_boolean_type() -> None:
    field = normalize_field("newsletter", "boolean")
    assert field.type == "boolean"
    assert field.required is False


def test_list_form_and_size_constraint() -> None:
    field = normalize_field("code", ["required", "string", "size:6"])
    assert field.required is True
    assert field.type == "string"
    assert field.constraints.size == 6.0
    assert field.raw_rules == ["required", "string", "size:6"]


def test_normalize_rules_preserves_field_order() -> None:
    fields = normalize_rules({"first": "required", "second": "email"})
    assert [f.name for f in fields] == ["first", "second"]
