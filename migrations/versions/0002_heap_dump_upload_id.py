"""Persist the idempotency key used to open a heap dump.

Revision ID: 0002_heap_dump_upload_id
Revises: 0001_initial_schema
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_heap_dump_upload_id"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("heap_dumps", sa.Column("upload_id", sa.String(), nullable=True))
    op.create_index("ix_heap_dumps_upload_id", "heap_dumps", ["upload_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_heap_dumps_upload_id", table_name="heap_dumps")
    op.drop_column("heap_dumps", "upload_id")
