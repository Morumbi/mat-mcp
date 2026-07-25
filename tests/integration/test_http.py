from pathlib import Path
from typing import cast

from fastmcp import Client, FastMCP
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mat_mcp.api.app import create_asgi_app, create_mcp_server
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.mat_query_service import MatQueryService
from mat_mcp.storage.filesystem import FileStorage


def create_test_app(tmp_path: Path) -> Starlette:
    heap_dumps = cast(HeapDumpService, object())
    storage = FileStorage(tmp_path, 1024)
    return create_asgi_app(create_mcp_server(heap_dumps, cast(MatQueryService, object())), storage)


def test_health_reports_process_liveness(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fastmcp_server_is_created() -> None:
    assert isinstance(
        create_mcp_server(cast(HeapDumpService, object()), cast(MatQueryService, object())), FastMCP
    )


def test_upload_stream_returns_one_time_identifier(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/uploads",
            content=b"JAVA PROFILE 1.0.2\x00payload",
            headers={"X-Filename": "heap.hprof"},
        )

    assert response.status_code == 201
    assert response.json()["upload_id"].startswith("upl_")
    assert response.json()["size"] > 0


class ErrorHeapDumpService:
    async def open_heap_dump(self, _: str) -> dict[str, object]:
        raise DomainError("invalid_input", "Invalid upload.")

    async def get_status(self, _: str) -> dict[str, object]:
        raise DomainError("heap_dump_not_found", "Heap dump was not found.")


async def test_tool_errors_set_mcp_is_error() -> None:
    server = create_mcp_server(
        cast(HeapDumpService, ErrorHeapDumpService()), cast(MatQueryService, object())
    )
    client = Client(server)

    async with client:
        result = await client.call_tool(
            "open_heap_dump", {"upload_id": "missing"}, raise_on_error=False
        )

    assert result.is_error is True
    assert result.content[0].text == (
        '{"error":{"code":"invalid_input","message":"Invalid upload.",'
        '"details":{},"retryable":false}}'
    )
