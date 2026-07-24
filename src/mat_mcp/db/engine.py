"""Async SQLite engine creation and connection pragmas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def database_url(database_path: Path) -> str:
    """Return a SQLite aiosqlite URL for a configured database path."""
    return f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"


def create_database_engine(database_path: Path, busy_timeout_ms: int) -> AsyncEngine:
    """Create an async engine that configures SQLite on every new connection."""
    engine = create_async_engine(database_url(database_path))

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        finally:
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create independent sessions for concurrent asyncio tasks."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine(engine: AsyncEngine) -> None:
    """Dispose the engine during application shutdown."""
    await engine.dispose()
