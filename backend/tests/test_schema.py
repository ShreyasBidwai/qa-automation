"""Migrations 0002–0005 applied cleanly and additively in the compose stack."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_TABLES = {
    "projects",
    "test_cases",
    "test_scripts",
    "runs",
    "results",
    "coverage",
    "model_nodes",
    "model_edges",
}
EXPECTED_ENUMS = {
    "test_type",
    "test_layer",
    "oracle_source",
    "authored_by",
    "framework",
    "run_trigger",
    "run_mode",
    "outcome",
    "triage",
    "coverage_dimension",
    "node_kind",
    "edge_kind",
}


async def test_migration_at_head(db_session: AsyncSession) -> None:
    revision = (
        await db_session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one()
    assert revision == "0005_node_embeddings"


async def test_model_nodes_has_embedding_column_and_hnsw_index(
    db_session: AsyncSession,
) -> None:
    column = (
        await db_session.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'model_nodes' AND column_name = 'embedding'"
            )
        )
    ).scalar_one_or_none()
    assert column is not None  # pgvector reports as USER-DEFINED

    indexes = set(
        (
            await db_session.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
        )
        .scalars()
        .all()
    )
    assert "ix_model_nodes_embedding_hnsw" in indexes


async def test_core_tables_and_enums_exist(db_session: AsyncSession) -> None:
    tables = set(
        (
            await db_session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        )
        .scalars()
        .all()
    )
    # projects (from 0001) is still present → the migration was additive.
    assert EXPECTED_TABLES <= tables

    enums = set(
        (
            await db_session.execute(
                text("SELECT typname FROM pg_type WHERE typtype = 'e'")
            )
        )
        .scalars()
        .all()
    )
    assert EXPECTED_ENUMS <= enums


async def test_required_indexes_exist(db_session: AsyncSession) -> None:
    indexes = set(
        (
            await db_session.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
        )
        .scalars()
        .all()
    )
    assert "ix_test_cases_project_id_type" in indexes
    assert "ix_model_nodes_project_id_source_sha" in indexes
    for fk_index in (
        "ix_test_cases_project_id",
        "ix_test_cases_parent_version_id",
        "ix_test_scripts_test_case_id",
        "ix_results_run_id",
        "ix_results_test_case_id",
        "ix_model_edges_src_node_id",
        "ix_model_edges_dst_node_id",
    ):
        assert fk_index in indexes
