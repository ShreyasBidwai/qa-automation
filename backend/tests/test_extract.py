"""The code extractor + PHP-header assembly (B5→B6, ADR-0037).

Correctness-critical for runnability — these pure transforms decide whether a
real model's output becomes a directly-runnable test. Exhaustive over the shapes a
model produces: clean code, a single fence, multiple fences, an unlabelled fence,
prose + fence + trailing table, and no fence at all. Generated tests are PHPUnit
feature CLASSES (the dialect both PHPUnit and Pest run), so the fixtures + the
class-name/method-name/skip helpers exercise that shape.
"""

from __future__ import annotations

from pathlib import Path

from app.generation.extract import (
    extract_code,
    phpunit_method_name,
    rewrite_class_name,
    skip_if_uses_factory,
    unique_class_name,
    with_comment_header,
    with_php_header,
)
from app.ingestion.laravel.factories import target_has_factories

_PROSE_WRAPPED = (
    "Here is the PHPUnit test for this endpoint. I used `postJson` so Laravel "
    "returns JSON.\n\n"
    "```php\n"
    "<?php\n\n"
    "namespace Tests\\Feature;\n\n"
    "use Tests\\TestCase;\n"
    "use Illuminate\\Foundation\\Testing\\RefreshDatabase;\n\n"
    "class StoresUserTest extends TestCase\n"
    "{\n"
    "    use RefreshDatabase;\n\n"
    "    public function test_stores_a_user(): void\n"
    "    {\n"
    "        $this->postJson('users', [])->assertStatus(422);\n"
    "    }\n"
    "}\n"
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
    assert "Here is the PHPUnit" not in code
    assert "class StoresUserTest extends TestCase" in code
    assert "public function test_stores_a_user" in code
    assert "assertStatus(422)" in code


def test_unlabelled_fence_is_extracted() -> None:
    text = "prose\n\n```\n<?php\nclass XTest extends TestCase {}\n```\n"
    assert extract_code(text) == "<?php\nclass XTest extends TestCase {}"


def test_multiple_fences_picks_the_largest_code_block() -> None:
    text = (
        "setup snippet:\n```php\n<?php // tiny\n```\n"
        "the full test:\n```php\n<?php\nclass BigTest extends TestCase {\n"
        "    public function test_big(): void {\n"
        "        $this->postJson('users', [])->assertStatus(422);\n    }\n}\n```\n"
    )
    code = extract_code(text)
    assert "class BigTest" in code and "// tiny" not in code


def test_prose_fence_loses_to_a_php_fence() -> None:
    text = (
        "```text\nthis is just an explanation block, not code at all really\n```\n"
        "```php\n<?php\nclass RealTest extends TestCase {}\n```\n"
    )
    assert "class RealTest" in extract_code(text)


def test_clean_code_passes_through_unchanged() -> None:
    clean = "// stub-generated\n// fingerprint: abc\n"
    assert extract_code(clean) == clean.strip()


def test_no_fence_strips_lead_in_prose() -> None:
    text = "Sure, here you go:\nAnd some more words.\n<?php\nclass XTest extends TestCase {}\n"
    assert extract_code(text) == "<?php\nclass XTest extends TestCase {}"


def test_empty_input_is_empty() -> None:
    assert extract_code("") == ""
    assert extract_code("   \n  ") == ""


# --- with_php_header ---------------------------------------------------------


def test_header_goes_after_php_open_tag_not_before() -> None:
    out = with_php_header("<?php\n\nclass XTest extends TestCase {}", "// h1\n// h2")
    assert out.startswith("<?php\n// h1\n// h2\n")
    assert out.count("<?php") == 1  # never a duplicate open tag
    assert "class XTest" in out


def test_header_adds_php_open_tag_when_missing() -> None:
    out = with_php_header("class XTest extends TestCase {}", "// header")
    assert out.startswith("<?php\n// header\n")


# --- with_comment_header (TS) ------------------------------------------------


def test_comment_header_precedes_ts_code() -> None:
    out = with_comment_header("import {test} from '@playwright/test';", "// e2e header")
    assert out == "// e2e header\n\nimport {test} from '@playwright/test';\n"


# --- class-name / method-name helpers ----------------------------------------


def test_method_name_is_a_valid_test_identifier() -> None:
    assert phpunit_method_name("name_required") == "test_name_required"
    assert phpunit_method_name("Create Thing!") == "test_create_thing"
    assert (
        phpunit_method_name("422 negative") == "test_c_422_negative"
    )  # never digit-led


def test_unique_class_name_is_readable_deterministic_and_collision_free() -> None:
    a = unique_class_name("happy", "POST api/users happy")
    again = unique_class_name("happy", "POST api/users happy")
    assert a == again  # deterministic
    assert a.startswith("Happy_") and a.endswith("Test")
    # A different endpoint with the SAME case name yields a DIFFERENT class name,
    # so two files never collide ("Cannot redeclare class") in one runner run.
    other = unique_class_name("happy", "POST api/orders happy")
    assert other != a
    # A non-letter-led case name still produces a valid PHP class identifier.
    assert unique_class_name("2nd", "x").startswith("Generated")


def test_rewrite_class_name_forces_the_first_class_declaration() -> None:
    code = (
        "<?php\nnamespace Tests\\Feature;\n"
        "class CaseAbcTest extends TestCase\n{\n}\n"
    )
    out = rewrite_class_name(code, "Happy_deadbeefTest")
    assert "class Happy_deadbeefTest extends TestCase" in out
    assert "CaseAbcTest" not in out


def test_rewrite_class_name_is_a_noop_without_a_class() -> None:
    code = "<?php\n// just a comment\n"
    assert rewrite_class_name(code, "XTest") == code


# --- skip_if_uses_factory (PHPUnit markTestSkipped) --------------------------


def test_factory_using_test_is_skipped_via_mark_test_skipped() -> None:
    code = (
        "<?php\nclass XTest extends TestCase\n{\n"
        "    public function test_x(): void\n    {\n"
        "        \\App\\Models\\Country::factory()->create();\n"
        "        $this->postJson('users', [])->assertStatus(422);\n    }\n}"
    )
    out = skip_if_uses_factory(code, "no factories")
    assert "$this->markTestSkipped('no factories');" in out
    # The skip runs BEFORE the factory call (it is the method's first statement).
    assert out.index("markTestSkipped") < out.index("::factory(")


def test_no_factory_is_left_untouched() -> None:
    code = (
        "<?php\nclass XTest extends TestCase\n{\n"
        "    public function test_x(): void\n    {\n"
        "        $this->get('/')->assertOk();\n    }\n}"
    )
    assert skip_if_uses_factory(code, "no factories") == code


def test_factory_without_a_method_shape_is_left_as_is() -> None:
    code = "<?php Country::factory()->create();"  # no test method to inject into
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
