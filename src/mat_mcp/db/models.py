"""SQLAlchemy models defined by the documented SQLite data model."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mat_mcp.db.base import Base


class HeapDump(Base):
    """Metadata for one indexed heap dump."""

    __tablename__ = "heap_dumps"
    __table_args__ = (
        CheckConstraint("status IN ('indexing', 'ready', 'failed')", name="ck_heap_dumps_status"),
        CheckConstraint(
            "original_type IN ('hprof', 'zip', 'gz')", name="ck_heap_dumps_original_type"
        ),
        CheckConstraint("content_type = 'hprof'", name="ck_heap_dumps_content_type"),
        CheckConstraint("source_size_bytes >= 0", name="ck_heap_dumps_source_size"),
        CheckConstraint("uncompressed_size_bytes >= 0", name="ck_heap_dumps_uncompressed_size"),
        CheckConstraint(
            "index_progress IS NULL OR index_progress BETWEEN 0 AND 100",
            name="ck_heap_dumps_index_progress",
        ),
        CheckConstraint(
            "error_retryable IS NULL OR error_retryable IN (0, 1)",
            name="ck_heap_dumps_error_retryable",
        ),
        Index("ix_heap_dumps_status", "status"),
        Index("ix_heap_dumps_expires_at", "expires_at"),
    )

    heap_dump_id: Mapped[str] = mapped_column(String, primary_key=True)
    upload_id: Mapped[str | None] = mapped_column(String, unique=True)
    content_sha256: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_type: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False, default="hprof")
    source_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uncompressed_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    hprof_path: Mapped[str] = mapped_column(String, nullable=False)
    index_path: Mapped[str] = mapped_column(String, nullable=False)
    index_stdout_path: Mapped[str | None] = mapped_column(String)
    index_stderr_path: Mapped[str | None] = mapped_column(String)
    index_progress: Mapped[int | None] = mapped_column(Integer)
    index_stage: Mapped[str | None] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details_json: Mapped[str | None] = mapped_column(Text)
    error_retryable: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    index_started_at: Mapped[str | None] = mapped_column(String)
    index_completed_at: Mapped[str | None] = mapped_column(String)


class MatQuery(Base):
    """Metadata for an individual MAT query attempt."""

    __tablename__ = "mat_queries"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('histogram', 'dominator_tree', 'path_to_gc_roots', "
            "'leak_suspects', 'oql', 'list_objects')",
            name="ck_mat_queries_operation",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')", name="ck_mat_queries_status"
        ),
        CheckConstraint("cache_hit IN (0, 1)", name="ck_mat_queries_cache_hit"),
        CheckConstraint(
            "truncated IS NULL OR truncated IN (0, 1)", name="ck_mat_queries_truncated"
        ),
        CheckConstraint(
            "error_retryable IS NULL OR error_retryable IN (0, 1)",
            name="ck_mat_queries_error_retryable",
        ),
        CheckConstraint("total_rows IS NULL OR total_rows >= 0", name="ck_mat_queries_total_rows"),
        CheckConstraint(
            "returned_rows IS NULL OR returned_rows >= 0", name="ck_mat_queries_returned_rows"
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_mat_queries_duration"),
        Index("ix_mat_queries_heap_dump_id", "heap_dump_id"),
        Index("ix_mat_queries_heap_dump_status", "heap_dump_id", "status"),
        Index(
            "ix_mat_queries_cache_lookup", "heap_dump_id", "request_hash", "status", "completed_at"
        ),
        Index("ix_mat_queries_created_at", "created_at"),
    )

    query_id: Mapped[str] = mapped_column(String, primary_key=True)
    heap_dump_id: Mapped[str] = mapped_column(
        ForeignKey("heap_dumps.heap_dump_id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String, nullable=False)
    request_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    cache_hit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_query_id: Mapped[str | None] = mapped_column(
        ForeignKey("mat_queries.query_id", ondelete="SET NULL")
    )
    query_directory_path: Mapped[str] = mapped_column(String, nullable=False)
    request_path: Mapped[str] = mapped_column(String, nullable=False)
    stdout_path: Mapped[str | None] = mapped_column(String)
    stderr_path: Mapped[str | None] = mapped_column(String)
    raw_result_path: Mapped[str | None] = mapped_column(String)
    result_path: Mapped[str | None] = mapped_column(String)
    total_rows: Mapped[int | None] = mapped_column(Integer)
    returned_rows: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details_json: Mapped[str | None] = mapped_column(Text)
    error_retryable: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String)
    completed_at: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
