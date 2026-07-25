"""Heap-dump lifecycle orchestration for the first vertical slice."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from mat_mcp.db.models import HeapDump
from mat_mcp.db.repositories import HeapDumpRepository
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.indexing_service import IndexingService, utc_now
from mat_mcp.storage.filesystem import FileStorage


class HeapDumpService:
    """Validates uploads, persists dump metadata, and starts indexing."""

    def __init__(
        self,
        storage: FileStorage,
        repository: HeapDumpRepository,
        indexer: IndexingService,
        ttl_seconds: int,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._indexer = indexer
        self._ttl_seconds = ttl_seconds

    async def open_heap_dump(self, upload_id: str) -> dict[str, object]:
        """Consume an upload and return promptly after scheduling MAT indexing."""
        heap_dump_id = f"hd_{uuid4().hex}"
        prepared = await self._storage.prepare_dump(upload_id, heap_dump_id)
        existing = await self._repository.find_by_hash(prepared.content_sha256)
        if existing is not None:
            self._storage.remove_workspace(prepared.workspace)
            return self._open_response(existing)
        now = utc_now()
        expires = (
            (datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=self._ttl_seconds))
            .isoformat()
            .replace("+00:00", "Z")
        )
        root = prepared.workspace.parent
        dump = HeapDump(
            heap_dump_id=heap_dump_id,
            content_sha256=prepared.content_sha256,
            status="indexing",
            filename=prepared.filename,
            original_type=prepared.original_type,
            content_type="hprof",
            source_size_bytes=prepared.source_size,
            uncompressed_size_bytes=prepared.uncompressed_size,
            storage_path=prepared.workspace.relative_to(root).as_posix(),
            hprof_path=prepared.hprof_path.relative_to(root).as_posix(),
            index_path=(prepared.workspace / "indexes").relative_to(root).as_posix(),
            index_stdout_path=(prepared.workspace / "indexing" / "stdout.log")
            .relative_to(root)
            .as_posix(),
            index_stderr_path=(prepared.workspace / "indexing" / "stderr.log")
            .relative_to(root)
            .as_posix(),
            index_progress=0,
            index_stage="Waiting for MAT indexing",
            created_at=now,
            updated_at=now,
            expires_at=expires,
        )
        try:
            await self._repository.add(dump)
        except IntegrityError:
            self._storage.remove_workspace(prepared.workspace)
            existing = await self._repository.find_by_hash(prepared.content_sha256)
            if existing is None:
                raise
            return self._open_response(existing)
        self._indexer.start(dump, prepared.workspace)
        return self._open_response(dump)

    async def get_status(self, heap_dump_id: str) -> dict[str, object]:
        """Return the stable public indexing state."""
        dump = await self._repository.find_by_id(heap_dump_id)
        if dump is None:
            raise DomainError(
                "heap_dump_not_found",
                "Heap dump was not found.",
                details={"heap_dump_id": heap_dump_id},
            )
        response: dict[str, object] = {
            "heap_dump_id": dump.heap_dump_id,
            "status": dump.status,
            "created_at": dump.created_at,
            "updated_at": dump.updated_at,
            "expires_at": dump.expires_at,
        }
        if dump.status in {"indexing", "ready"}:
            response.update({"progress": dump.index_progress, "stage": dump.index_stage})
        if dump.status == "failed":
            response["error"] = {
                "code": dump.error_code,
                "message": dump.error_message,
                "details": {},
                "retryable": bool(dump.error_retryable),
            }
        return response

    async def close_heap_dump(self, heap_dump_id: str) -> dict[str, object]:
        """Stop active work and remove a dump workspace and its metadata.

        Missing metadata means an earlier close already completed, so the public
        operation stays idempotent.
        """
        dump = await self._repository.find_by_id(heap_dump_id)
        if dump is None:
            return {"heap_dump_id": heap_dump_id, "closed": True, "deleted": True}
        await self._indexer.stop(heap_dump_id)
        try:
            workspace = self._storage.workspace_for(dump.storage_path)
            await asyncio.to_thread(self._storage.remove_workspace, workspace)
        except (OSError, ValueError) as error:
            raise DomainError(
                "close_failed", "Heap dump resources could not be deleted.", retryable=True
            ) from error
        await self._repository.delete_by_id(heap_dump_id)
        return {"heap_dump_id": heap_dump_id, "closed": True, "deleted": True}

    @staticmethod
    def _open_response(dump: HeapDump) -> dict[str, object]:
        return {
            "heap_dump_id": dump.heap_dump_id,
            "status": dump.status,
            "filename": dump.filename,
            "original_type": dump.original_type,
            "content_type": dump.content_type,
            "size": dump.source_size_bytes,
            "uncompressed_size": dump.uncompressed_size_bytes,
            "created_at": dump.created_at,
            "expires_at": dump.expires_at,
        }
