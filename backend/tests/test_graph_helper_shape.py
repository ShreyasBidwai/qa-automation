"""Graph-helper integration (real php + nikic/php-parser) — closes mock drift.

Marked ``runner``: runs ONLY in the runners/laravel image. Runs the real
extract_graph.php against the committed fixture app and asserts its JSON parses
into EXACTLY the RepoGraph the LaravelIngester consumes — so the canned output
the fast tests pin can never drift from the real helper (same pattern as
T1.3/T1.5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.commands import check_output, run_subprocess
from app.ingestion.laravel.graph import parse_graph_output

pytestmark = pytest.mark.runner

APP_PATH = Path(__file__).parent / "fixtures" / "laravel-app"
HELPER = (
    Path(__file__).parents[1]
    / "app"
    / "ingestion"
    / "laravel"
    / "php"
    / "extract_graph.php"
)


def test_graph_helper_output_matches_ingester_contract() -> None:
    result = run_subprocess(["php", str(HELPER), str(APP_PATH)], None, 60.0)
    stdout = check_output(result, what="php graph helper")
    graph = parse_graph_output(stdout)

    # Models — class, convention table, fillable, declared relationships.
    models = {m.cls: m for m in graph.models}
    assert "App\\Models\\User" in models
    assert "App\\Models\\Country" in models
    user = models["App\\Models\\User"]
    assert user.table == "users"
    assert user.fillable == ["name", "email", "age", "country_id", "newsletter"]
    assert ("belongsTo", "App\\Models\\Country") in {
        (r.kind, r.related) for r in user.relationships
    }
    country = models["App\\Models\\Country"]
    assert country.table == "countries"
    assert ("hasMany", "App\\Models\\User") in {
        (r.kind, r.related) for r in country.relationships
    }

    # Migrations — table + derivable columns.
    migrations = {m.table: m for m in graph.migrations}
    assert {"users", "countries"} <= set(migrations)
    assert {"id", "name", "email", "age", "country_id", "newsletter"} <= set(
        migrations["users"].columns
    )
    assert {"id", "name"} <= set(migrations["countries"].columns)

    # Actions — statically referenced model + validation summary.
    actions = {(a.controller, a.action): a for a in graph.actions}
    store = actions[("App\\Http\\Controllers\\UserController", "store")]
    assert "App\\Models\\User" in store.model_refs
    assert store.validation.source == "form_request"
    assert "email" in store.validation.fields
