from fastmcp import Client

from mat_mcp.api.app import create_mcp_server
from mat_mcp.domain.errors import DomainError


class FailingHeapDumps:
    async def open_heap_dump(self, _: str) -> dict[str, object]:
        raise DomainError("invalid_input", "Upload was not found.")

    async def get_status(self, _: str) -> dict[str, object]:
        raise DomainError("heap_dump_not_found", "Heap dump was not found.")


class FailingQueries:
    async def run(self, *_: object) -> dict[str, object]:
        raise DomainError("query_failed", "MAT query failed.")


async def test_domain_error_is_an_mcp_error_result() -> None:
    client = Client(create_mcp_server(FailingHeapDumps(), FailingQueries()))

    async with client:
        result = await client.call_tool(
            "open_heap_dump", {"upload_id": "upl_missing"}, raise_on_error=False
        )

    assert result.is_error is True
    assert result.content[0].type == "text"
    assert '"code":"invalid_input"' in result.content[0].text
