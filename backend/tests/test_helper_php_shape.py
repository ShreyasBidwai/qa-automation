"""PHP-helper integration (real php + nikic/php-parser) — closes T1.3 mock drift.

Marked ``runner``: runs ONLY in the ``runners/laravel`` image (php + the
fixture's composer vendor are absent from the fast suite). Runs the real
`extract_validation.php` against the committed Laravel fixture and asserts its
JSON output is EXACTLY what the Python validation normalizer consumes — so the
canned outputs the offline tests pin can never drift from the real helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.commands import check_output, run_subprocess
from app.ingestion.laravel.normalize import normalize_rules
from app.ingestion.laravel.validation import parse_helper_output

pytestmark = pytest.mark.runner

APP_PATH = Path(__file__).parent / "fixtures" / "laravel-app"
HELPER = (
    Path(__file__).parents[1]
    / "app"
    / "ingestion"
    / "laravel"
    / "php"
    / "extract_validation.php"
)


def test_helper_output_matches_normalizer_contract() -> None:
    result = run_subprocess(
        [
            "php",
            str(HELPER),
            str(APP_PATH),
            "App\\Http\\Controllers\\UserController",
            "store",
        ],
        None,
        60.0,
    )
    stdout = check_output(result, what="php validation helper")
    extraction = parse_helper_output(stdout)

    # 1. The real helper emits exactly the rule strings the Python side pins.
    assert extraction.source == "form_request"
    assert extraction.rules == {
        "name": "required|string|max:255",
        "email": "required|email|unique:users,email",
        "age": "required|integer|min:18|max:120",
        "country_id": "required|exists:countries,id",
        "newsletter": "boolean",
    }

    # 2. The normalizer turns that shape into the same typed fields the
    #    generator/plan rely on — the contract holds end to end.
    fields = {f.name: f for f in normalize_rules(extraction.rules)}
    assert fields["name"].required is True and fields["name"].constraints.max == 255
    assert fields["email"].type == "email"
    assert fields["email"].relational is not None
    assert fields["email"].relational.kind == "unique"
    assert fields["email"].relational.table == "users"
    assert fields["age"].type == "integer"
    assert fields["age"].constraints.min == 18
    assert fields["age"].constraints.max == 120
    assert fields["country_id"].relational is not None
    assert fields["country_id"].relational.kind == "exists"
    assert fields["country_id"].relational.table == "countries"
    assert fields["newsletter"].type == "boolean"
    assert fields["newsletter"].required is False
