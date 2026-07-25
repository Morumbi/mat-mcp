"""Explicit database operations for heap-dump metadata."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mat_mcp.db.models import HeapDump, MatQuery


class HeapDumpRepository:
    """Repository that keeps SQL out of MCP handlers and services."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def find_by_id(self, heap_dump_id: str) -> HeapDump | None:
        async with self._sessions() as session:
            return await session.get(HeapDump, heap_dump_id)

    async def find_by_hash(self, content_sha256: str) -> HeapDump | None:
        async with self._sessions() as session:
            result = await session.scalar(
                select(HeapDump).where(HeapDump.content_sha256 == content_sha256)
            )
            return result

    async def add(self, dump: HeapDump) -> None:
        async with self._sessions() as session:
            session.add(dump)
            await session.commit()

    async def delete_by_id(self, heap_dump_id: str) -> bool:
        """Delete a dump and its MAT queries through the database cascade."""
        async with self._sessions() as session:
            dump = await session.get(HeapDump, heap_dump_id)
            if dump is None:
                return False
            await session.delete(dump)
            await session.commit()
            return True

    async def mark_ready(self, heap_dump_id: str, updated_at: str) -> None:
        async with self._sessions() as session:
            dump = await session.get(HeapDump, heap_dump_id)
            if dump is not None:
                dump.status, dump.index_progress, dump.index_stage = (
                    "ready",
                    100,
                    "Indexing completed",
                )
                dump.updated_at = dump.index_completed_at = updated_at
                await session.commit()

    async def mark_failed(self, heap_dump_id: str, message: str, updated_at: str) -> None:
        async with self._sessions() as session:
            dump = await session.get(HeapDump, heap_dump_id)
            if dump is not None:
                dump.status, dump.error_code, dump.error_message = (
                    "failed",
                    "indexing_failed",
                    message,
                )
                dump.error_retryable, dump.updated_at, dump.index_completed_at = (
                    0,
                    updated_at,
                    updated_at,
                )
                await session.commit()


class MatQueryRepository:
    """Persists completed MAT query attempts."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def add(self, query: MatQuery) -> None:
        async with self._sessions() as session:
            session.add(query)
            await session.commit()
