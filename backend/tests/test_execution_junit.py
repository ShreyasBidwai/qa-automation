"""JUnit parsing — pass/fail/error/skipped mapping from canned Pest output."""

from __future__ import annotations

import pytest

from app.execution.errors import JUnitParseError
from app.execution.junit import parse_junit
from app.models.enums import Outcome

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="Feature" tests="4" failures="1" errors="1">
    <testcase name="happy path" classname="P\\Tests\\Feature\\Happy"
              file="/app/tests/Feature/_generated/happy.php" time="0.10"/>
    <testcase name="missing name" classname="P\\Tests\\Feature\\Missing"
              file="/app/tests/Feature/_generated/missing.php" time="0.05">
      <failure type="PHPUnit\\Framework\\ExpectationFailedException">expected 201, got 422</failure>
    </testcase>
    <testcase name="boom" classname="P\\Tests\\Feature\\Boom"
              file="/app/tests/Feature/_generated/boom.php" time="0.01">
      <error type="Error">undefined method</error>
    </testcase>
    <testcase name="later" classname="P\\Tests\\Feature\\Later"
              file="/app/tests/Feature/_generated/later.php" time="0.0">
      <skipped/>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_parse_junit_maps_each_status() -> None:
    cases = parse_junit(_XML)
    by_name = {c.name: c for c in cases}
    assert by_name["happy path"].outcome is Outcome.PASS
    assert by_name["happy path"].message is None
    assert by_name["missing name"].outcome is Outcome.FAIL
    assert "expected 201" in (by_name["missing name"].message or "")
    assert by_name["boom"].outcome is Outcome.ERROR
    assert by_name["later"].outcome is Outcome.ERROR  # skipped == did not run
    # The file attribute is preserved (used to map results back to scripts).
    assert by_name["happy path"].file.endswith("happy.php")  # type: ignore[union-attr]


def test_parse_junit_rejects_malformed_xml() -> None:
    with pytest.raises(JUnitParseError):
        parse_junit("<testsuites><testcase>")  # truncated
