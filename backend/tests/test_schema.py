"""Migrations 0002–0024 applied cleanly and additively in the compose stack."""

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
    "auth_challenge_log",
    "findings",
    "finding_results",
    "finding_triage",
    "users",
    "sessions",
    "password_reset_tokens",
    "organizations",
    "organization_members",
    "organization_invites",
    "jobs",
    "project_documents",
    "document_chunks",
    "spec_divergences",
    "test_heals",
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
    "case_origin",
    "proposal_status",
    "auth_challenge",
    "finding_layer",
    "triage_status",
    "org_role",
    "job_kind",
    "job_status",
}


async def test_migration_at_head(db_session: AsyncSession) -> None:
    revision = (
        await db_session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one()
    assert revision == "0025_db_state_tier"


async def test_projects_has_app_url_and_soft_delete_columns(
    db_session: AsyncSession,
) -> None:
    columns = set(
        (
            await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'projects'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert {"app_url", "deleted_at"} <= columns  # Sprint B1 (0016)
    # B3 (0019): org-scoped; owner_id renamed to created_by (ADR-0032).
    assert {"org_id", "created_by"} <= columns
    assert "owner_id" not in columns
    assert "db_state_tier" in columns  # B10 (0025), ADR-0043


async def test_model_nodes_has_embedding_column_and_hnsw_index(
    db_session: AsyncSession,
) -> None:
    columns = set(
        (
            await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'model_nodes'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert {"embedding", "content_sha"} <= columns  # T2.3 + T2.6 columns

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
    assert "ix_model_nodes_project_id_content_sha" in indexes


async def test_test_cases_has_lineage_columns(db_session: AsyncSession) -> None:
    columns = set(
        (
            await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'test_cases'"
                )
            )
        )
        .scalars()
        .all()
    )
    # T3 lineage/versioning columns added additively over the T1.1 schema.
    assert {"lineage_id", "is_current", "origin", "edited_by"} <= columns
    # T3.2 merge/proposal columns.
    assert {"case_key", "proposal_status"} <= columns
    # T3.3 proposal-resolution provenance columns.
    assert {"resolved_by", "resolved_at"} <= columns


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
    assert "ix_test_cases_project_id_lineage_id" in indexes  # T3 lineage history
    assert "uq_test_cases_one_current" in indexes  # T3 one-current invariant
    assert "ix_test_cases_project_id_case_key" in indexes  # T3.2 re-gen matching
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
