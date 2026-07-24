from pathlib import Path

from sqlalchemy import text

from mat_mcp.db.engine import create_database_engine
from mat_mcp.main import run_migrations


async def test_engine_enables_required_sqlite_pragmas(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "metadata.db", 3210)
    try:
        async with engine.connect() as connection:
            foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one()
            busy_timeout = (await connection.execute(text("PRAGMA busy_timeout"))).scalar_one()
            journal_mode = (await connection.execute(text("PRAGMA journal_mode"))).scalar_one()
    finally:
        await engine.dispose()

    assert foreign_keys == 1
    assert busy_timeout == 3210
    assert journal_mode == "wal"


async def test_migrations_are_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "metadata.db"

    run_migrations(database)
    run_migrations(database)

    engine = create_database_engine(database, 5000)

    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
            names = set(rows.scalars())
    finally:
        await engine.dispose()

    assert {"heap_dumps", "mat_queries", "alembic_version"} <= names
