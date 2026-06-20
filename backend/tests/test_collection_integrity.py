"""Guard: no test can be silently dropped from collection (suite integrity).

The suite sets ``python_classes = ["*Tests"]`` (pyproject.toml) on purpose: many
domain classes are named ``Test*`` — ``TestCase``, ``TestType``, ``TestScript``,
``TestLayer`` … — and are imported into test modules, so pytest's default
``Test*`` prefix would try to collect *them* as test classes. The cost of that
choice is the inverse trap: a test class written with the conventional ``Test*``
prefix matches nothing and is dropped **without warning** — it looks like it
protects us but never runs (this bit feat/finding-detail-fields).

For a product whose thesis is trustworthy tests, that hole can't exist. This
meta-test reads the *active* collection config and fails if any ``def test_*``
lives in a class pytest won't collect — catching the mistake at the one place it
would otherwise pass unnoticed, while keeping the deliberate ``*Tests`` choice.
"""

from __future__ import annotations

import ast
import fnmatch
import pathlib

import pytest

_TESTS_DIR = pathlib.Path(__file__).parent


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def test_no_test_methods_live_in_uncollected_classes(
    pytestconfig: pytest.Config,
) -> None:
    """Every class holding ``def test_*`` must match ``python_classes``."""
    class_patterns = pytestconfig.getini("python_classes")
    func_patterns = pytestconfig.getini("python_functions")
    file_patterns = pytestconfig.getini("python_files")

    offenders: list[str] = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        if not _matches_any(path.name, file_patterns):
            continue  # not a file pytest would collect as a test module
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        # Module-level classes only — that's the scope pytest collects from a
        # module's namespace, and the scope of the naming trap.
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            has_test_method = any(
                isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and _matches_any(child.name, func_patterns)
                for child in node.body
            )
            if has_test_method and not _matches_any(node.name, class_patterns):
                offenders.append(f"{path.relative_to(_TESTS_DIR)}::{node.name}")

    assert not offenders, (
        "Test methods live in classes pytest will NOT collect with "
        f"python_classes={class_patterns} (they would run as zero tests). "
        f"Rename each to end in 'Tests': {', '.join(offenders)}"
    )
