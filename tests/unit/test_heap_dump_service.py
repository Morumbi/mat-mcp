import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast

from mat_mcp.db.models import HeapDump
from mat_mcp.db.repositories import HeapDumpRepository
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.indexing_service import IndexingService
from mat_mcp.storage.filesystem import FileStorage


async def chunks(value: bytes):
    yield value


async def wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Background preparation did not finish in time.")


class FakeRepository:
    def __init__(self) -> None:
        self.dump: HeapDump | None = None

    async def find_by_hash(self, _: str) -> HeapDump | None:
        return self.dump

    async def find_by_upload_id(self, upload_id: str) -> HeapDump | None:
        if self.dump is not None and self.dump.upload_id == upload_id:
            return self.dump
        return None

    async def add(self, dump: HeapDump) -> None:
        self.dump = dump

    async def update_prepared(
        self, _: str, content_sha256: str, uncompressed_size: int, __: str
    ) -> bool:
        assert self.dump is not None
        self.dump.content_sha256 = content_sha256
        self.dump.uncompressed_size_bytes = uncompressed_size
        self.dump.index_stage = "Waiting for MAT indexing"
        return True

    async def find_by_id(self, _: str) -> HeapDump | None:
        return self.dump

    async def delete_by_id(self, _: str) -> bool:
        if self.dump is None:
            return False
        self.dump = None
        return True


class FakeIndexer:
    def __init__(self) -> None:
        self.started = False

    def start(self, _: HeapDump, __: Path) -> None:
        self.started = True

    async def stop(self, _: str) -> None:
        self.started = False


async def test_open_starts_indexing_and_exposes_status(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, 1024)
    upload = await storage.store_upload("heap.hprof", chunks(b"JAVA PROFILE 1.0.2\x00payload"))
    repository = FakeRepository()
    indexer = FakeIndexer()
    service = HeapDumpService(
        storage,
        cast(HeapDumpRepository, repository),
        cast(IndexingService, indexer),
        ttl_seconds=60,
    )

    opened = await service.open_heap_dump(upload.upload_id)
    await wait_until(lambda: indexer.started)
    status = await service.get_status(cast(str, opened["heap_dump_id"]))

    assert opened["status"] == "indexing"
    assert status["stage"] in {"Preparing heap dump", "Waiting for MAT indexing"}
    assert indexer.started


async def test_repeated_open_returns_the_existing_heap_dump_id(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, 1024)
    upload = await storage.store_upload("heap.hprof", chunks(b"JAVA PROFILE 1.0.2\x00payload"))
    repository = FakeRepository()
    service = HeapDumpService(
        storage,
        cast(HeapDumpRepository, repository),
        cast(IndexingService, FakeIndexer()),
        ttl_seconds=60,
    )

    first = await service.open_heap_dump(upload.upload_id)
    repeated = await service.open_heap_dump(upload.upload_id)

    assert repeated == first


async def test_close_removes_workspace_metadata_and_is_idempotent(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, 1024)
    upload = await storage.store_upload("heap.hprof", chunks(b"JAVA PROFILE 1.0.2\x00payload"))
    repository = FakeRepository()
    indexer = FakeIndexer()
    service = HeapDumpService(
        storage,
        cast(HeapDumpRepository, repository),
        cast(IndexingService, indexer),
        ttl_seconds=60,
    )
    opened = await service.open_heap_dump(upload.upload_id)
    heap_dump_id = cast(str, opened["heap_dump_id"])
    await wait_until(lambda: (tmp_path / heap_dump_id).exists())
    assert (tmp_path / heap_dump_id).exists()

    closed = await service.close_heap_dump(heap_dump_id)
    repeated = await service.close_heap_dump(heap_dump_id)

    assert closed == {"heap_dump_id": heap_dump_id, "closed": True, "deleted": True}
    assert repeated == closed
    assert repository.dump is None
    assert not (tmp_path / heap_dump_id).exists()
