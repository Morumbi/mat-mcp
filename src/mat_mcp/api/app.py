"""ASGI composition for Streamable HTTP MCP and health."""

import json
from typing import NoReturn

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from mat_mcp.api.health import health
from mat_mcp.api.uploads import create_upload_endpoint
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.mat_query_service import MatQueryService
from mat_mcp.storage.filesystem import FileStorage


def raise_tool_error(error: DomainError) -> NoReturn:
    """Map a domain failure to FastMCP's schema-compliant tool error."""
    raise ToolError(json.dumps(error.as_response(), separators=(",", ":"))) from error


def create_mcp_server(heap_dumps: HeapDumpService, queries: MatQueryService) -> FastMCP:
    """Create the MCP server with thin handlers over application services."""
    mcp = FastMCP("MAT MCP")

    @mcp.tool()
    async def open_heap_dump(upload_id: str) -> dict[str, object]:
        """Open an uploaded HPROF, ZIP, or GZIP heap dump and start indexing."""
        try:
            return await heap_dumps.open_heap_dump(upload_id)
        except DomainError as error:
            raise_tool_error(error)

    @mcp.tool()
    async def get_heap_dump_status(heap_dump_id: str) -> dict[str, object]:
        """Return the current MAT indexing state of a heap dump."""
        try:
            return await heap_dumps.get_status(heap_dump_id)
        except DomainError as error:
            raise_tool_error(error)

    @mcp.tool()
    async def run_mat_query(
        heap_dump_id: str, operation: str, data: dict[str, object]
    ) -> dict[str, object]:
        """Run the currently supported MAT histogram query."""
        try:
            return await queries.run(heap_dump_id, operation, data)
        except DomainError as error:
            raise_tool_error(error)

    return mcp


def create_asgi_app(mcp: FastMCP, storage: FileStorage) -> Starlette:
    """Expose only Streamable HTTP MCP plus the liveness endpoint."""
    mcp_app = mcp.http_app(path="/mcp")
    return Starlette(
        routes=[
            Route("/health", health),
            Route("/uploads", create_upload_endpoint(storage), methods=["POST"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.lifespan,
    )
