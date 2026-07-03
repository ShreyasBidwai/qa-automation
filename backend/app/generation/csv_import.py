"""CSV-driven test authoring (QA-authored scenarios → runnable tests).

A QA human declares test scenarios in a CSV; each row becomes a DETERMINISTIC,
directly-runnable PHPUnit/Pest test — no AI, so imports are reproducible, free, and
never hallucinate. The QA stated the expected outcome, so the oracle is honestly
``spec-grounded`` and the case is ``origin=authored`` / ``authored_by=human``.

Pure + deterministic (same CSV → same tests): parsing/validation and rendering have
no I/O, so they are exhaustively unit-testable. Persistence (idempotent merge) lives
in the service layer. Bad rows are reported per-row, never silently dropped (§7).
See ADR-0058 for the design (why no AI, why spec-grounded, the merge/key strategy).

CSV format (header row required; column names case-insensitive, spaces→underscores):

  method,path,expected_status[,name][,payload][,description][,authenticated]

- method           GET | POST | PUT | PATCH | DELETE               (required)
- path             the endpoint URI, e.g. ``api/v1/orders/1``       (required)
- expected_status  the HTTP status to assert, e.g. 200/201/422      (required)
- name             short test name (derived from method+path if omitted)
- payload          a JSON object body (POST/PUT/PATCH), e.g. {"qty":2}
- description       what the scenario verifies (rendered as an // Intent comment)
- authenticated    true (default) | false — act as a factory user or not
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.generation.extract import unique_class_name, with_php_header
from app.models.enums import (
    AuthoredBy,
    CaseOrigin,
    Framework,
    OracleSource,
    TestLayer,
    TestType,
)
from app.models.test_case import TestCase
from app.models.test_script import TestScript

# Bound an import so a pathological upload can't wedge the request (mirrors the
# document-upload caps). Excess rows are reported, never silently truncated.
MAX_CSV_ROWS = 500

_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_JSON_HELPER = {
    "GET": "getJson",
    "POST": "postJson",
    "PUT": "putJson",
    "PATCH": "patchJson",
    "DELETE": "deleteJson",
}
_REQUIRED_COLUMNS = frozenset({"method", "path", "expected_status"})


@dataclass(frozen=True)
class CsvTestSpec:
    """One validated CSV row — a QA-declared test scenario."""

    name: str
    method: str
    path: str
    expected_status: int
    payload: dict[str, Any] | None
    description: str
    authenticated: bool


@dataclass(frozen=True)
class CsvRowError:
    """A row that failed validation (``row`` is 1-based, excluding the header)."""

    row: int
    message: str


@dataclass(frozen=True)
class CsvParseResult:
    specs: tuple[CsvTestSpec, ...]
    errors: tuple[CsvRowError, ...]


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def parse_csv_tests(content: str) -> CsvParseResult:
    """Parse + validate a CSV of test scenarios. Never raises — a malformed row
    becomes a ``CsvRowError`` so the operator sees exactly what to fix."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return CsvParseResult((), (CsvRowError(0, "empty CSV — need a header row"),))
    columns = {_norm(name): name for name in reader.fieldnames}
    missing = _REQUIRED_COLUMNS - set(columns)
    if missing:
        detail = ", ".join(sorted(missing))
        return CsvParseResult((), (CsvRowError(0, f"missing column(s): {detail}"),))

    specs: list[CsvTestSpec] = []
    errors: list[CsvRowError] = []
    for index, raw in enumerate(reader, start=1):
        if index > MAX_CSV_ROWS:
            errors.append(CsvRowError(index, f"row limit {MAX_CSV_ROWS} exceeded"))
            break
        # A wholly-blank line (trailing newline etc.) is skipped, not an error.
        if not any((raw.get(src) or "").strip() for src in columns.values()):
            continue
        spec, message = _row_to_spec(raw, columns)
        if spec is not None:
            specs.append(spec)
        else:
            errors.append(CsvRowError(index, message))

    return CsvParseResult(tuple(specs), tuple(errors))


def _row_to_spec(
    raw: dict[str, str], columns: dict[str, str]
) -> tuple[CsvTestSpec | None, str]:
    def cell(key: str) -> str:
        return (raw.get(columns.get(key, ""), "") or "").strip()

    problems: list[str] = []

    method = cell("method").upper()
    if method not in _METHODS:
        problems.append(f"method {cell('method')!r} must be one of {sorted(_METHODS)}")

    path = cell("path")
    if not path:
        problems.append("path is required")

    status = 0
    status_raw = cell("expected_status")
    try:
        status = int(status_raw)
        if not (100 <= status <= 599):
            raise ValueError
    except ValueError:
        problems.append(f"expected_status {status_raw!r} is not a valid HTTP status")

    payload: dict[str, Any] | None = None
    payload_raw = cell("payload")
    if payload_raw:
        try:
            loaded = json.loads(payload_raw)
        except json.JSONDecodeError:
            loaded = None
            problems.append("payload is not valid JSON")
        if loaded is not None and not isinstance(loaded, dict):
            problems.append('payload must be a JSON object (e.g. {"qty": 2})')
        elif isinstance(loaded, dict):
            payload = loaded

    if problems:
        return None, "; ".join(problems)

    # ``authenticated`` defaults to true; only explicit false/no/0 opts out.
    authenticated = cell("authenticated").lower() not in ("false", "no", "0")
    name = cell("name") or f"{method} {path}"
    return (
        CsvTestSpec(
            name=name,
            method=method,
            path=path,
            expected_status=status,
            payload=payload,
            description=cell("description"),
            authenticated=authenticated,
        ),
        "",
    )


# --- deterministic PHP rendering (no AI) -------------------------------------


def _php_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int | float):
        return repr(value)
    return _php_string(str(value))


def _php_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _php_literal(value: Any) -> str:
    if isinstance(value, dict):
        inner = ", ".join(
            f"{_php_string(str(k))} => {_php_literal(v)}" for k, v in value.items()
        )
        return f"[{inner}]"
    if isinstance(value, list):
        return "[" + ", ".join(_php_literal(v) for v in value) + "]"
    return _php_scalar(value)


def _method_identifier(name: str) -> str:
    slug = re.sub(r"\W+", "_", name.lower()).strip("_")
    return slug or "case"


def _header(spec: CsvTestSpec) -> str:
    lines = [
        f"// CSV-authored test: {spec.name}",
        "// oracle_source: spec-grounded (the QA declared the expected outcome)",
    ]
    if spec.description:
        lines.append(f"// Intent: {spec.description}")
    return "\n".join(lines)


def render_csv_test(spec: CsvTestSpec) -> str:
    """A directly-runnable PHPUnit/Pest feature test for one CSV row (deterministic).

    The class name is a deterministic globally-unique value so several imported files
    never collide in one runner invocation."""
    class_name = unique_class_name(spec.name, f"{spec.method}|{spec.path}|{spec.name}")
    helper = _JSON_HELPER[spec.method]
    path_literal = _php_string(spec.path)
    if spec.payload is not None and spec.method != "GET":
        call = f"$this->{helper}({path_literal}, {_php_literal(spec.payload)})"
    else:
        call = f"$this->{helper}({path_literal})"

    setup = (
        "        $this->actingAs(\\App\\Models\\User::factory()->create());\n"
        if spec.authenticated
        else ""
    )
    code = (
        "namespace Tests\\Feature;\n\n"
        "use Illuminate\\Foundation\\Testing\\RefreshDatabase;\n"
        "use Tests\\TestCase;\n\n"
        f"class {class_name} extends TestCase\n"
        "{\n"
        "    use RefreshDatabase;\n\n"
        f"    public function test_{_method_identifier(spec.name)}(): void\n"
        "    {\n"
        f"{setup}"
        f"        $response = {call};\n"
        f"        $response->assertStatus({spec.expected_status});\n"
        "    }\n"
        "}"
    )
    return with_php_header(code, _header(spec))


# --- persistence shapes (merged idempotently by the service) -----------------


def csv_case_key(spec: CsvTestSpec) -> str:
    """Stable identity so re-importing the same scenario UPDATES it in place (never a
    duplicate). Shaped ``"{METHOD} {path}::csv::{hash}"`` — the readable prefix makes
    the Tests viewer show the endpoint (it labels from ``case_key.split("::")[0]``),
    while the ``csv`` segment + hash keep the full key unique and namespaced: the AI
    generator's keys use a real case type there (happy/negative/edge), never ``csv``,
    so the two authoring paths never collide on a full key."""
    seed = f"csv|{spec.method}|{spec.path}|{spec.name}|{spec.expected_status}"
    digest = hashlib.sha256(seed.encode()).hexdigest()[:16]
    return f"{spec.method} {spec.path}::csv::{digest}"


def to_test_case(project_id: uuid.UUID, spec: CsvTestSpec, case_key: str) -> TestCase:
    return TestCase(
        project_id=project_id,
        type=TestType.HAPPY if spec.expected_status < 400 else TestType.NEGATIVE,
        layer=TestLayer.API,
        target_node=None,
        preconditions={
            "endpoint": {"method": spec.method, "uri": spec.path},
            "authenticated": spec.authenticated,
            "source": "csv",
        },
        steps={
            "method": spec.method,
            "uri": spec.path,
            "payload": spec.payload,
            "authenticated": spec.authenticated,
            "case": spec.name,
        },
        expected={"status": spec.expected_status, "shape": {}},
        # The QA stated the expectation → spec-grounded, human-authored.
        oracle_source=OracleSource.SPEC_GROUNDED,
        authored_by=AuthoredBy.HUMAN,
        # Authored via import, not hand-edited in the case editor — so a corrected
        # re-upload UPDATES in place rather than forking a protected proposal.
        edited_by_human=False,
        origin=CaseOrigin.AUTHORED,
        case_key=case_key,
    )


def to_test_script(
    project_id: uuid.UUID, test_case_id: uuid.UUID, code: str
) -> TestScript:
    return TestScript(
        project_id=project_id,
        test_case_id=test_case_id,
        framework=Framework.PEST,
        code=code,
        generated_by="csv-import",
        deterministic=True,
    )
