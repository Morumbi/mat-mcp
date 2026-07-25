"""Non-blocking Eclipse MAT indexing process orchestration."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from mat_mcp.db.models import HeapDump
from mat_mcp.db.repositories import HeapDumpRepository


def utc_now() -> str:
    """Return a documented UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class IndexingService:
    """Launches one MAT subprocess per heap dump and records its outcome."""

    def __init__(
        self,
        executable_path: Path,
        max_heap: str,
        timeout_seconds: int,
        repository: HeapDumpRepository,
    ) -> None:
        self._executable_path = executable_path.resolve()
        self._max_heap = max_heap
        self._timeout_seconds = timeout_seconds
        self._repository = repository
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, dump: HeapDump, workspace: Path) -> None:
        """Schedule indexing without blocking the MCP request handler."""
        task = asyncio.create_task(self._run(dump, workspace), name=f"index-{dump.heap_dump_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, dump: HeapDump, workspace: Path) -> None:
        log_dir = workspace / "indexing"
        log_dir.mkdir(exist_ok=True)
        stdout_path, stderr_path = log_dir / "stdout.log", log_dir / "stderr.log"
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(
                    str(self._executable_path),
                    str(workspace / "heap" / "heap.hprof"),
                    stdout=stdout,
                    stderr=stderr,
                    env={**os.environ, "JAVA_TOOL_OPTIONS": f"-Xmx{self._max_heap}"},
                )
                await asyncio.wait_for(process.wait(), timeout=self._timeout_seconds)
            if process.returncode != 0:
                await self._repository.mark_failed(
                    dump.heap_dump_id, "MAT indexing process failed.", utc_now()
                )
                return
            await self._repository.mark_ready(dump.heap_dump_id, utc_now())
        except TimeoutError:
            await self._repository.mark_failed(
                dump.heap_dump_id, "MAT indexing timed out.", utc_now()
            )
        except Exception:
            await self._repository.mark_failed(
                dump.heap_dump_id, "MAT indexing could not be started.", utc_now()
            )
