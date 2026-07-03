"""CSV-driven test authoring (QA-authored scenarios → runnable tests).

A QA human declares test scenarios in a CSV; each row becomes a DETERMINISTIC,
directly-runnable PHPUnit/Pest test — no AI, so imports are reproducible, free, and
never hallucinate. The QA stated the expected outcome, so the oracle is honestly
``spec-grounded`` and the case is ``origin=authored`` / ``authored_by=human``.

Pure + deterministic (same CSV → same tests): parsing/validation and rendering have
no I/O, so they are exhaustively unit-testable. Persistence (idempotent merge) lives
in the service layer. Bad rows are reported per-row, never silently dropped (§7).
See ADR-0058 for the design (why no AI, why spec-grounded, the merge/key strategy).

CSV format (header row required; column names case-insensitive, spaces→underscores).
``path`` is the only universally-required column; the rest depend on the layer:

  [layer,]path,method,expected_status[,name][,payload][,description][,authenticated]
  [,assert_text]

- layer            api (default) | ui — API endpoint test, or a UI page smoke
- path             the endpoint URI (api) or page path (ui), e.g. ``api/v1/orders/1``
- method           GET | POST | PUT | PATCH | DELETE   (required for api; n/a for ui)
- expected_status  the HTTP status to assert (required for api; ui defaults to "loads")
- name             short test name (derived from the path if omitted)
- payload          a JSON object body (POST/PUT/PATCH, api only), e.g. {"qty":2}
- description       what the scenario verifies (rendered as an // Intent comment)
- authenticated    true (default) | false — act as a factory user (api only)
- assert_text      (ui only) text that must be visible on the page after it loads

An ``api`` row renders a deterministic PHPUnit/Pest feature test; a ``ui`` row renders
a Playwright page-smoke spec (visit ``path``, assert it loaded, optionally assert text).
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
_LAYERS = frozenset({"api", "ui"})
# ``path`` is the only universally-required column; ``method``/``expected_status`` are
# required per-row for the API layer (validated in _row_to_spec), not at the header.
_REQUIRED_COLUMNS = frozenset({"path"})
# A UI page-smoke row asserts the page loaded (< 400) when no status is given.
_UI_DEFAULT_STATUS = 200


@dataclass(frozen=True)
class CsvTestSpec:
    """One validated CSV row — a QA-declared test scenario.

    ``layer`` is ``api`` (an endpoint request/response, rendered as PHPUnit/Pest) or
    ``ui`` (a page-smoke: visit ``path`` and assert it loads, rendered as Playwright).
    ``assert_text`` (UI only) additionally asserts that text is visible on the page.
    """

    name: str
    method: str
    path: str
    expected_status: int
    payload: dict[str, Any] | None
    description: str
    authenticated: bool
    layer: str = "api"
    assert_text: str | None = None


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

    layer = (cell("layer") or "api").lower()
    if layer not in _LAYERS:
        return None, f"layer {cell('layer')!r} must be one of {sorted(_LAYERS)}"
    return _ui_row(cell) if layer == "ui" else _api_row(cell)


def _api_row(cell: Any) -> tuple[CsvTestSpec | None, str]:
    """An API-layer row: an endpoint request with a fixed expected status."""
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
            layer="api",
        ),
        "",
    )


def _ui_row(cell: Any) -> tuple[CsvTestSpec | None, str]:
    """A UI-layer row: a page smoke — visit ``path``, assert it loads (< 400), and
    optionally assert some text is visible. ``method``/``payload`` don't apply."""
    path = cell("path")
    if not path:
        return None, "path is required"

    status_raw = cell("expected_status")
    status = _UI_DEFAULT_STATUS
    if status_raw:
        try:
            status = int(status_raw)
            if not (100 <= status <= 599):
                raise ValueError
        except ValueError:
            return None, f"expected_status {status_raw!r} is not a valid HTTP status"

    authenticated = cell("authenticated").lower() not in ("false", "no", "0")
    name = cell("name") or f"VISIT {path}"
    return (
        CsvTestSpec(
            name=name,
            method="GET",
            path=path,
            expected_status=status,
            payload=None,
            description=cell("description"),
            authenticated=authenticated,
            layer="ui",
            assert_text=cell("assert_text") or None,
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


def _js_string(value: str) -> str:
    """A double-quoted JS string literal, escaped (for the Playwright spec)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_csv_ui_test(spec: CsvTestSpec) -> str:
    """A directly-runnable Playwright ``.spec.ts`` page-smoke for one UI CSV row.

    Visits ``path`` (relative → resolved against the harness ``baseURL``), asserts the
    page loaded (status < 400, or the exact status if the QA pinned one), and — when
    ``assert_text`` is given — that the text is visible. Deterministic (no AI)."""
    title = f"{spec.name} (CSV page smoke)"
    path_literal = _js_string(spec.path)
    lines = [
        'import { test, expect } from "@playwright/test";',
        "",
        f"// CSV-authored UI test: {spec.name}",
        "// oracle_source: spec-grounded (the QA declared the expected outcome)",
    ]
    if spec.description:
        lines.append(f"// Intent: {spec.description}")
    lines += [
        f"test({_js_string(title)}, async ({{ page }}) => {{",
        f"  const response = await page.goto({path_literal});",
    ]
    # A pinned 4xx/5xx asserts that exact status; otherwise just "the page loaded".
    if spec.expected_status >= 400:
        lines.append(f"  expect(response?.status()).toBe({spec.expected_status});")
    else:
        lines.append("  expect(response?.status() ?? 0).toBeLessThan(400);")
    if spec.assert_text:
        lines.append(
            f"  await expect(page.getByText({_js_string(spec.assert_text)}))"
            ".toBeVisible();"
        )
    lines.append("});")
    return "\n".join(lines) + "\n"


def render_csv_test(spec: CsvTestSpec) -> str:
    """A directly-runnable test for one CSV row (deterministic, no AI).

    Dispatches by layer: an API row → a PHPUnit/Pest feature test; a UI row → a
    Playwright page-smoke spec. The PHPUnit class name is a deterministic globally-
    unique value so several imported files never collide in one runner invocation."""
    if spec.layer == "ui":
        return render_csv_ui_test(spec)
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
    duplicate). Shaped ``"{label}::csv::{hash}"`` — the readable prefix (``METHOD
    path`` for API, ``VISIT path`` for UI) makes the Tests viewer show the target (it
    labels from ``case_key.split("::")[0]``), while the ``csv`` segment + hash keep
    the full key unique and namespaced: the AI generator's keys use a real case type
    there (happy/negative/edge), never ``csv``, so the two authoring paths never
    collide on a full key. The hash includes the layer, so an API and a UI row on the
    same path get distinct lineages."""
    label = f"VISIT {spec.path}" if spec.layer == "ui" else f"{spec.method} {spec.path}"
    seed = (
        f"csv|{spec.layer}|{spec.method}|{spec.path}"
        f"|{spec.name}|{spec.expected_status}"
    )
    digest = hashlib.sha256(seed.encode()).hexdigest()[:16]
    return f"{label}::csv::{digest}"


def to_test_case(project_id: uuid.UUID, spec: CsvTestSpec, case_key: str) -> TestCase:
    is_ui = spec.layer == "ui"
    if is_ui:
        preconditions: dict[str, Any] = {
            "page": {"path": spec.path},
            "assert_text": spec.assert_text,
            "source": "csv",
        }
        steps: dict[str, Any] = {
            "action": "visit",
            "path": spec.path,
            "assert_text": spec.assert_text,
            "case": spec.name,
        }
    else:
        preconditions = {
            "endpoint": {"method": spec.method, "uri": spec.path},
            "authenticated": spec.authenticated,
            "source": "csv",
        }
        steps = {
            "method": spec.method,
            "uri": spec.path,
            "payload": spec.payload,
            "authenticated": spec.authenticated,
            "case": spec.name,
        }
    return TestCase(
        project_id=project_id,
        type=TestType.HAPPY if spec.expected_status < 400 else TestType.NEGATIVE,
        layer=TestLayer.UI if is_ui else TestLayer.API,
        target_node=None,
        preconditions=preconditions,
        steps=steps,
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
    project_id: uuid.UUID, test_case_id: uuid.UUID, code: str, *, layer: str = "api"
) -> TestScript:
    return TestScript(
        project_id=project_id,
        test_case_id=test_case_id,
        framework=Framework.PLAYWRIGHT if layer == "ui" else Framework.PEST,
        code=code,
        generated_by="csv-import",
        deterministic=True,
    )
