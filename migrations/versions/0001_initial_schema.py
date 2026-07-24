"""Initial heap dump and MAT query metadata schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create documented MVP metadata tables and indexes."""
    op.create_table(
        "heap_dumps",
        sa.Column("heap_dump_id", sa.String(), nullable=False),
        sa.Column("content_sha256", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("original_type", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("uncompressed_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("hprof_path", sa.String(), nullable=False),
        sa.Column("index_path", sa.String(), nullable=False),
        sa.Column("index_stdout_path", sa.String()),
        sa.Column("index_stderr_path", sa.String()),
        sa.Column("index_progress", sa.Integer()),
        sa.Column("index_stage", sa.String()),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_details_json", sa.Text()),
        sa.Column("error_retryable", sa.Integer()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("index_started_at", sa.String()),
        sa.Column("index_completed_at", sa.String()),
        sa.CheckConstraint(
            "status IN ('indexing', 'ready', 'failed')", name="ck_heap_dumps_status"
        ),
        sa.CheckConstraint(
            "original_type IN ('hprof', 'zip', 'gz')", name="ck_heap_dumps_original_type"
        ),
        sa.CheckConstraint("content_type = 'hprof'", name="ck_heap_dumps_content_type"),
        sa.CheckConstraint("source_size_bytes >= 0", name="ck_heap_dumps_source_size"),
        sa.CheckConstraint("uncompressed_size_bytes >= 0", name="ck_heap_dumps_uncompressed_size"),
        sa.CheckConstraint(
            "index_progress IS NULL OR index_progress BETWEEN 0 AND 100",
            name="ck_heap_dumps_index_progress",
        ),
        sa.CheckConstraint(
            "error_retryable IS NULL OR error_retryable IN (0, 1)",
            name="ck_heap_dumps_error_retryable",
        ),
        sa.PrimaryKeyConstraint("heap_dump_id"),
        sa.UniqueConstraint("content_sha256", name="ux_heap_dumps_content_sha256"),
    )
    op.create_index("ix_heap_dumps_status", "heap_dumps", ["status"])
    op.create_index("ix_heap_dumps_expires_at", "heap_dumps", ["expires_at"])
    op.create_table(
        "mat_queries",
        sa.Column("query_id", sa.String(), nullable=False),
        sa.Column("heap_dump_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("request_data_json", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("cache_hit", sa.Integer(), nullable=False),
        sa.Column("cached_query_id", sa.String()),
        sa.Column("query_directory_path", sa.String(), nullable=False),
        sa.Column("request_path", sa.String(), nullable=False),
        sa.Column("stdout_path", sa.String()),
        sa.Column("stderr_path", sa.String()),
        sa.Column("raw_result_path", sa.String()),
        sa.Column("result_path", sa.String()),
        sa.Column("total_rows", sa.Integer()),
        sa.Column("returned_rows", sa.Integer()),
        sa.Column("truncated", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_details_json", sa.Text()),
        sa.Column("error_retryable", sa.Integer()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String()),
        sa.Column("completed_at", sa.String()),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            (
                "operation IN ('histogram', 'dominator_tree', 'path_to_gc_roots', "
                "'leak_suspects', 'oql', 'list_objects')"
            ),
            name="ck_mat_queries_operation",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_mat_queries_status"
        ),
        sa.CheckConstraint("cache_hit IN (0, 1)", name="ck_mat_queries_cache_hit"),
        sa.CheckConstraint(
            "truncated IS NULL OR truncated IN (0, 1)", name="ck_mat_queries_truncated"
        ),
        sa.CheckConstraint(
            "error_retryable IS NULL OR error_retryable IN (0, 1)",
            name="ck_mat_queries_error_retryable",
        ),
        sa.CheckConstraint(
            "total_rows IS NULL OR total_rows >= 0", name="ck_mat_queries_total_rows"
        ),
        sa.CheckConstraint(
            "returned_rows IS NULL OR returned_rows >= 0", name="ck_mat_queries_returned_rows"
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_mat_queries_duration"
        ),
        sa.ForeignKeyConstraint(["heap_dump_id"], ["heap_dumps.heap_dump_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cached_query_id"], ["mat_queries.query_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("query_id"),
    )
    op.create_index("ix_mat_queries_heap_dump_id", "mat_queries", ["heap_dump_id"])
    op.create_index("ix_mat_queries_heap_dump_status", "mat_queries", ["heap_dump_id", "status"])
    op.create_index(
        "ix_mat_queries_cache_lookup",
        "mat_queries",
        ["heap_dump_id", "request_hash", "status", "completed_at"],
    )
    op.create_index("ix_mat_queries_created_at", "mat_queries", ["created_at"])


def downgrade() -> None:
    """Remove the initial schema."""
    op.drop_table("mat_queries")
    op.drop_table("heap_dumps")
