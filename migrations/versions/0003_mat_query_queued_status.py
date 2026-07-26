"""Allow persisted MAT queries to wait for a worker slot.

Revision ID: 0003_mat_query_queued_status
Revises: 0002_heap_dump_upload_id
"""

from alembic import op


revision = "0003_mat_query_queued_status"
down_revision = "0002_heap_dump_upload_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mat_queries") as batch:
        batch.drop_constraint("ck_mat_queries_status", type_="check")
        batch.create_check_constraint(
            "ck_mat_queries_status",
            "status IN ('queued', 'running', 'completed', 'failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("mat_queries") as batch:
        batch.drop_constraint("ck_mat_queries_status", type_="check")
        batch.create_check_constraint(
            "ck_mat_queries_status",
            "status IN ('running', 'completed', 'failed')",
        )
