"""CSV test authoring — the pure parse + deterministic render core (no DB, no AI).

The parser turns a QA's CSV into validated scenarios, reporting bad rows rather than
dropping them; the renderer turns each scenario into a directly-runnable PHPUnit test.
Both are pure, so they're pinned exhaustively here (persistence is tested at the API).
"""

from __future__ import annotations

from app.generation.csv_import import (
    MAX_CSV_ROWS,
    csv_case_key,
    parse_csv_tests,
    render_csv_test,
)
from app.models.enums import (
    AuthoredBy,
    CaseOrigin,
    OracleSource,
    TestType,
)

_GOOD = (
    "name,method,path,expected_status,payload,description,authenticated\n"
    "List orders,GET,api/v1/orders,200,,lists orders,true\n"
    'Create order,POST,api/v1/orders,201,"{""qty"": 2}",creates one,true\n'
    'Reject bad qty,POST,api/v1/orders,422,"{""qty"": -1}",negative,true\n'
)


def test_parses_valid_rows_into_typed_specs() -> None:
    result = parse_csv_tests(_GOOD)
    assert not result.errors
    assert [s.name for s in result.specs] == [
        "List orders",
        "Create order",
        "Reject bad qty",
    ]
    create = result.specs[1]
    assert create.method == "POST"
    assert create.path == "api/v1/orders"
    assert create.expected_status == 201
    assert create.payload == {"qty": 2}
    assert create.authenticated is True


def test_headers_are_case_insensitive_and_name_defaults() -> None:
    # Column names normalise (case/space-insensitive); a missing name derives from
    # method+path; authenticated defaults to true when the column is absent.
    csv = "Method, Path ,Expected Status\nget,api/health,200\n"
    result = parse_csv_tests(csv)
    assert not result.errors
    spec = result.specs[0]
    assert spec.method == "GET" and spec.name == "GET api/health"
    assert spec.authenticated is True and spec.payload is None


def test_authenticated_false_variants_opt_out() -> None:
    csv = "method,path,expected_status,authenticated\nGET,api/x,200,false\n"
    assert parse_csv_tests(csv).specs[0].authenticated is False


def test_missing_required_column_is_a_whole_file_error() -> None:
    # No expected_status column at all → one row-0 error, no specs.
    result = parse_csv_tests("method,path\nGET,api/x\n")
    assert not result.specs
    assert result.errors[0].row == 0
    assert "expected_status" in result.errors[0].message


def test_bad_rows_are_reported_not_dropped() -> None:
    csv = (
        "method,path,expected_status,payload\n"
        "FETCH,api/x,200,\n"  # bad method
        "GET,,200,\n"  # missing path
        "GET,api/x,999,\n"  # out-of-range status
        "POST,api/x,201,not-json\n"  # invalid JSON payload
        "POST,api/x,201,[1]\n"  # JSON but not an object
        "GET,api/ok,200,\n"  # the one good row
    )
    result = parse_csv_tests(csv)
    assert [s.path for s in result.specs] == ["api/ok"]
    assert {e.row for e in result.errors} == {1, 2, 3, 4, 5}
    assert "method" in result.errors[0].message
    assert "path" in result.errors[1].message
    assert "status" in result.errors[2].message
    assert "JSON" in result.errors[3].message


def test_blank_lines_are_skipped_silently() -> None:
    csv = "method,path,expected_status\nGET,api/x,200\n\n,,\nGET,api/y,200\n"
    result = parse_csv_tests(csv)
    assert [s.path for s in result.specs] == ["api/x", "api/y"]
    assert not result.errors


def test_empty_csv_reports_a_header_error() -> None:
    result = parse_csv_tests("")
    assert not result.specs and result.errors[0].row == 0


def test_row_limit_is_enforced_and_reported() -> None:
    rows = "\n".join(f"GET,api/r{i},200" for i in range(MAX_CSV_ROWS + 5))
    result = parse_csv_tests("method,path,expected_status\n" + rows + "\n")
    assert len(result.specs) == MAX_CSV_ROWS
    assert any("limit" in e.message for e in result.errors)


def test_render_is_runnable_pest_and_grounded() -> None:
    spec = parse_csv_tests(_GOOD).specs[1]  # POST create with a payload
    code = render_csv_test(spec)
    assert code.startswith("<?php")
    assert "namespace Tests\\Feature;" in code
    assert "extends TestCase" in code
    assert "use RefreshDatabase;" in code
    # The exact request the QA declared — method helper, path, payload, status.
    assert "$this->postJson('api/v1/orders', ['qty' => 2])" in code
    assert "assertStatus(201)" in code
    # Authenticated rows act as a factory user; the intent is a code comment.
    assert "User::factory()->create()" in code
    assert "// Intent: creates one" in code


def test_render_is_deterministic() -> None:
    spec = parse_csv_tests(_GOOD).specs[0]
    assert render_csv_test(spec) == render_csv_test(spec)


def test_unauthenticated_render_omits_the_acting_user() -> None:
    csv = "method,path,expected_status,authenticated\nGET,api/public,200,false\n"
    code = render_csv_test(parse_csv_tests(csv).specs[0])
    assert "factory()" not in code
    assert "$this->getJson('api/public')" in code


def test_php_string_escaping_is_injection_safe() -> None:
    # A path/value containing a quote must not break out of the PHP literal.
    csv = "method,path,expected_status\nGET,api/x'; drop,200\n"
    code = render_csv_test(parse_csv_tests(csv).specs[0])
    assert "api/x\\'; drop" in code  # single quote escaped, not terminated


def test_case_key_is_stable_readable_and_namespaced() -> None:
    spec = parse_csv_tests(_GOOD).specs[0]  # "List orders" → GET api/v1/orders
    key = csv_case_key(spec)
    # Readable prefix (the viewer shows METHOD path) + a "csv" segment the AI never
    # emits as a case type, so a CSV key can't collide with an AI key on the full key.
    assert key.startswith("GET api/v1/orders::csv::")
    assert csv_case_key(spec) == key  # stable → idempotent re-import


def test_status_class_drives_test_type_via_the_builder() -> None:
    from app.generation.csv_import import to_test_case

    happy, negative = parse_csv_tests(_GOOD).specs[0], parse_csv_tests(_GOOD).specs[2]
    import uuid

    pid = uuid.uuid4()
    happy_case = to_test_case(pid, happy, csv_case_key(happy))
    negative_case = to_test_case(pid, negative, csv_case_key(negative))
    assert happy_case.type is TestType.HAPPY
    assert negative_case.type is TestType.NEGATIVE
    # A CSV scenario is honestly human-authored + spec-grounded (the QA declared it),
    # and NOT flagged hand-edited so a corrected re-upload updates in place.
    assert happy_case.authored_by is AuthoredBy.HUMAN
    assert happy_case.origin is CaseOrigin.AUTHORED
    assert happy_case.oracle_source is OracleSource.SPEC_GROUNDED
    assert happy_case.edited_by_human is False
