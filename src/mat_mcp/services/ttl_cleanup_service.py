"""Periodic deletion of heap dumps whose fixed retention time has elapsed."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from mat_mcp.db.repositories import HeapDumpRepository
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.indexing_service import utc_now

logger = logging.getLogger(__name__)


class TtlCleanupService:
    """Run explicit-close semantics for every expired heap dump."""

    def __init__(
        self,
        repository: HeapDumpRepository,
        heap_dumps: HeapDumpService,
        interval_seconds: int,
    ) -> None:
        self._repository = repository
        self._heap_dumps = heap_dumps
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        """Start background cleanup once the ASGI lifespan has started."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ttl-cleanup")

    async def stop(self) -> None:
        """Stop the periodic task during graceful ASGI shutdown."""
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> int:
        """Delete all dumps expired at the start of this cleanup pass."""
        async with self._lock:
            deleted = 0
            for heap_dump_id in await self._repository.find_expired_ids(utc_now()):
                try:
                    await self._heap_dumps.close_heap_dump(heap_dump_id)
                except DomainError:
                    logger.warning("TTL cleanup failed for heap dump %s", heap_dump_id, exc_info=True)
                else:
                    deleted += 1
            return deleted

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("TTL cleanup pass failed")
            await asyncio.sleep(self._interval_seconds)
