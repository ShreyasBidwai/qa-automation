"""The code extractor + PHP-header assembly (B5→B6, ADR-0037).

Correctness-critical for runnability — these pure transforms decide whether a
real model's output becomes a directly-runnable test. Exhaustive over the shapes a
model produces: clean code, a single fence, multiple fences, an unlabelled fence,
prose + fence + trailing table, and no fence at all.
"""

from __future__ import annotations

from pathlib import Path

from app.generation.extract import (
    extract_code,
    skip_if_uses_factory,
    with_comment_header,
    with_php_header,
)
from app.ingestion.laravel.factories import target_has_factories

_PROSE_WRAPPED = (
    "Here is the Pest test for this endpoint. I used `postJson` so Laravel returns "
    "JSON.\n\n"
    "```php\n"
    "<?php\n\n"
    "uses(\\Illuminate\\Foundation\\Testing\\RefreshDatabase::class);\n\n"
    "it('stores a user', function () {\n"
    "    $this->postJson('users', [])->assertStatus(422);\n"
    "});\n"
    "```\n\n"
    "**Key decisions:**\n\n"
    "| Decision | Reason |\n|---|---|\n| postJson | JSON envelope |\n"
)


# --- extract_code ------------------------------------------------------------


def test_extracts_php_from_prose_and_fence_and_table() -> None:
    code = extract_code(_PROSE_WRAPPED)
    assert code.startswith("<?php")
    assert "```" not in code
    assert "Key decisions" not in code
    assert "Here is the Pest" not in code
    assert "it('stores a user'" in code and "assertStatus(422)" in code


def test_unlabelled_fence_is_extracted() -> None:
    text = "prose\n\n```\n<?php\nit('x', fn() => 1);\n```\n"
    assert extract_code(text) == "<?php\nit('x', fn() => 1);"


def test_multiple_fences_picks_the_largest_code_block() -> None:
    text = (
        "setup snippet:\n```php\n<?php // tiny\n```\n"
        "the full test:\n```php\n<?php\nit('big', function () {\n"
        "    $this->postJson('users', [])->assertStatus(422);\n});\n```\n"
    )
    code = extract_code(text)
    assert "it('big'" in code and "// tiny" not in code


def test_prose_fence_loses_to_a_php_fence() -> None:
    text = (
        "```text\nthis is just an explanation block, not code at all really\n```\n"
        "```php\n<?php\nit('real', fn() => 1);\n```\n"
    )
    assert "it('real'" in extract_code(text)


def test_clean_code_passes_through_unchanged() -> None:
    clean = "// stub-generated\n// fingerprint: abc\n"
    assert extract_code(clean) == clean.strip()


def test_no_fence_strips_lead_in_prose() -> None:
    text = "Sure, here you go:\nAnd some more words.\n<?php\nit('x', fn() => 1);\n"
    assert extract_code(text) == "<?php\nit('x', fn() => 1);"


def test_empty_input_is_empty() -> None:
    assert extract_code("") == ""
    assert extract_code("   \n  ") == ""


# --- with_php_header ---------------------------------------------------------


def test_header_goes_after_php_open_tag_not_before() -> None:
    out = with_php_header("<?php\n\nit('x', fn() => 1);", "// h1\n// h2")
    assert out.startswith("<?php\n// h1\n// h2\n")
    assert out.count("<?php") == 1  # never a duplicate open tag
    assert "it('x'" in out


def test_header_adds_php_open_tag_when_missing() -> None:
    out = with_php_header("it('x', fn() => 1);", "// header")
    assert out.startswith("<?php\n// header\n")


# --- with_comment_header (TS) ------------------------------------------------


def test_comment_header_precedes_ts_code() -> None:
    out = with_comment_header("import {test} from '@playwright/test';", "// e2e header")
    assert out == "// e2e header\n\nimport {test} from '@playwright/test';\n"


# --- skip_if_uses_factory ----------------------------------------------------


def test_factory_using_test_is_skipped() -> None:
    code = (
        "<?php\nit('x', function () {\n"
        "    \\App\\Models\\Country::factory()->create();\n"
        "    $this->postJson('users', [])->assertStatus(422);\n});"
    )
    out = skip_if_uses_factory(code, "no factories")
    assert "->skip('no factories')" in out
    assert out.rstrip().endswith("->skip('no factories');")


def test_no_factory_is_left_untouched() -> None:
    code = "<?php\nit('x', function () {\n    $this->get('/')->assertOk();\n});"
    assert skip_if_uses_factory(code, "no factories") == code


def test_factory_without_closing_shape_is_left_as_is() -> None:
    code = "<?php Country::factory()->create();"  # no `});` to chain onto
    assert skip_if_uses_factory(code, "r") == code


# --- target_has_factories (ADR-0037 detection) -------------------------------


def test_target_has_factories_detects_all_cases(tmp_path: Path) -> None:
    assert target_has_factories("") is False  # no repo
    assert target_has_factories(str(tmp_path)) is False  # no database/factories
    factories = tmp_path / "database" / "factories"
    factories.mkdir(parents=True)
    assert target_has_factories(str(tmp_path)) is False  # dir present, no *.php
    (factories / "UserFactory.php").write_text("<?php")
    assert target_has_factories(str(tmp_path)) is True
