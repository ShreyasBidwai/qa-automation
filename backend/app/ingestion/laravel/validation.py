"""Extract validation rules for a controller action via the PHP AST helper.

The PHP helper (php/extract_validation.php) uses nikic/php-parser to resolve the
action's type-hinted FormRequest `rules()` OR an inline `$request->validate([…])`
and emits the rule set as JSON. This module only invokes it (through the
injectable runner) and parses its JSON — never the PHP source itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ingestion.commands import CommandRunner, check_output
from app.ingestion.errors import ValidationExtractionError


@dataclass(frozen=True)
class ValidationExtraction:
    source: str  # form_request | inline_validate | none
    rules: dict[str, str | list[str]] = field(default_factory=dict)


def parse_helper_output(stdout: str) -> ValidationExtraction:
    try:
        data: Any = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValidationExtractionError(
            "php validation helper did not return valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise ValidationExtractionError("php helper output is not an object")

    rules_obj = data.get("rules", {})
    if not isinstance(rules_obj, dict):
        raise ValidationExtractionError("php helper 'rules' is not an object")

    rules: dict[str, str | list[str]] = {}
    for key, value in rules_obj.items():
        if isinstance(value, list):
            rules[str(key)] = [str(item) for item in value]
        else:
            rules[str(key)] = str(value)

    return ValidationExtraction(source=str(data.get("source", "none")), rules=rules)


def extract_validation(
    *,
    repo_path: str,
    controller_fqcn: str,
    action: str,
    runner: CommandRunner,
    php_path: str,
    helper_script: str,
    timeout: float,
) -> ValidationExtraction:
    argv = [php_path, helper_script, repo_path, controller_fqcn, action]
    result = runner(argv, None, timeout)
    stdout = check_output(result, what="php validation helper")
    return parse_helper_output(stdout)
