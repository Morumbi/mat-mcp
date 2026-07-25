from typing import cast

from mat_mcp.db.repositories import HeapDumpRepository
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.ttl_cleanup_service import TtlCleanupService


class ExpiredRepository:
    async def find_expired_ids(self, _: str) -> list[str]:
        return ["hd_expired", "hd_failed"]


class ClosingHeapDumps:
    def __init__(self) -> None:
        self.closed: list[str] = []

    async def close_heap_dump(self, heap_dump_id: str) -> dict[str, object]:
        self.closed.append(heap_dump_id)
        if heap_dump_id == "hd_failed":
            raise DomainError("close_failed", "Workspace is locked.", retryable=True)
        return {"heap_dump_id": heap_dump_id, "closed": True, "deleted": True}


async def test_cleanup_uses_close_for_each_expired_dump_and_continues_on_failure() -> None:
    repository = ExpiredRepository()
    heap_dumps = ClosingHeapDumps()
    cleanup = TtlCleanupService(
        cast(HeapDumpRepository, repository), cast(HeapDumpService, heap_dumps), 60
    )

    deleted = await cleanup.run_once()

    assert deleted == 1
    assert heap_dumps.closed == ["hd_expired", "hd_failed"]
