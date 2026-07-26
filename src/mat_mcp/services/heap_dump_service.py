"""Heap-dump lifecycle orchestration for the first vertical slice."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from mat_mcp.db.models import HeapDump
from mat_mcp.db.repositories import HeapDumpRepository
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.indexing_service import IndexingService, utc_now
from mat_mcp.storage.filesystem import FileStorage, Upload

logger = logging.getLogger("mat_mcp")


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
        self._preparation_tasks: dict[str, asyncio.Task[None]] = {}
        self._uploads: dict[str, HeapDump] = {}

    async def open_heap_dump(self, upload_id: str) -> dict[str, object]:
        """Consume an upload and schedule preparation independently of the client request."""
        known_dump = self._uploads.get(upload_id)
        if known_dump is not None:
            return self._open_response(known_dump)
        persisted_dump = await self._repository.find_by_upload_id(upload_id)
        if persisted_dump is not None:
            self._uploads[upload_id] = persisted_dump
            return self._open_response(persisted_dump)
        heap_dump_id = f"hd_{uuid4().hex}"
        upload = self._storage.claim_upload(upload_id)
        now = utc_now()
        expires = (
            (datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=self._ttl_seconds))
            .isoformat()
            .replace("+00:00", "Z")
        )
        dump = HeapDump(
            heap_dump_id=heap_dump_id,
            upload_id=upload_id,
            content_sha256=f"preparing:{heap_dump_id}",
            status="indexing",
            filename=upload.filename,
            original_type=upload.original_type,
            content_type="hprof",
            source_size_bytes=upload.size,
            uncompressed_size_bytes=0,
            storage_path=heap_dump_id,
            hprof_path=f"{heap_dump_id}/heap/heap.hprof",
            index_path=f"{heap_dump_id}/indexes",
            index_stdout_path=f"{heap_dump_id}/indexing/stdout.log",
            index_stderr_path=f"{heap_dump_id}/indexing/stderr.log",
            index_progress=0,
            index_stage="Preparing heap dump",
            created_at=now,
            updated_at=now,
            expires_at=expires,
        )
        self._uploads[upload_id] = dump
        try:
            await self._repository.add(dump)
        except Exception:
            self._uploads.pop(upload_id, None)
            raise
        task = asyncio.create_task(
            self._prepare_and_start(dump, upload), name=f"prepare-{heap_dump_id}"
        )
        self._preparation_tasks[heap_dump_id] = task
        task.add_done_callback(
            lambda completed: self._preparation_tasks.pop(heap_dump_id, None)
            if self._preparation_tasks.get(heap_dump_id) is completed
            else None
        )
        return self._open_response(dump)

    async def _prepare_and_start(self, dump: HeapDump, upload: Upload) -> None:
        """Finish file preparation after the MCP response has already been returned."""
        try:
            prepared = await self._storage.prepare_claimed_upload(upload, dump.heap_dump_id)
            existing = await self._repository.find_by_hash(prepared.content_sha256)
            if existing is not None and existing.heap_dump_id != dump.heap_dump_id:
                self._storage.remove_workspace(prepared.workspace)
                await self._repository.mark_failed(
                    dump.heap_dump_id, "An identical heap dump is already open.", utc_now()
                )
                return
            saved = await self._repository.update_prepared(
                dump.heap_dump_id,
                prepared.content_sha256,
                prepared.uncompressed_size,
                utc_now(),
            )
            if saved:
                dump.content_sha256 = prepared.content_sha256
                dump.uncompressed_size_bytes = prepared.uncompressed_size
                dump.index_stage = "Waiting for MAT indexing"
                self._indexer.start(dump, prepared.workspace)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heap dump preparation failed for %s", dump.heap_dump_id)
            await self._repository.mark_failed(
                dump.heap_dump_id, "Heap dump preparation failed.", utc_now()
            )

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
        task = self._preparation_tasks.pop(heap_dump_id, None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._indexer.stop(heap_dump_id)
        try:
            workspace = self._storage.workspace_for(dump.storage_path)
            await asyncio.to_thread(self._storage.remove_workspace, workspace)
        except (OSError, ValueError) as error:
            raise DomainError(
                "close_failed", "Heap dump resources could not be deleted.", retryable=True
            ) from error
        await self._repository.delete_by_id(heap_dump_id)
        stale_upload_ids = [
            upload_id
            for upload_id, mapped_dump in self._uploads.items()
            if mapped_dump.heap_dump_id == heap_dump_id
        ]
        for upload_id in stale_upload_ids:
            self._uploads.pop(upload_id, None)
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
