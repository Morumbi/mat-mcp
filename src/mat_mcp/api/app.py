"""ASGI composition for Streamable HTTP MCP and health."""

import json
from typing import Annotated, Literal, NoReturn

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from mat_mcp.api.health import health
from mat_mcp.api.uploads import create_upload_endpoint
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.mat_query_service import MatQueryService
from mat_mcp.storage.filesystem import FileStorage

QueryOperation = Literal[
    "histogram",
    "dominator_tree",
    "path_to_gc_roots",
    "leak_suspects",
    "oql",
    "list_objects",
]

QueryData = Annotated[
    dict[str, object],
    Field(
        description=(
            "Parameters depend on operation. histogram, dominator_tree, and leak_suspects "
            "require {}. path_to_gc_roots requires {object_address: '0x...'}. "
            "oql requires {query: 'SELECT ...'}; only one SELECT expression is allowed. "
            "list_objects requires {class_name: 'fully.qualified.Class'} and accepts "
            "optional include_subclasses: boolean."
        ),
        json_schema_extra={
            "oneOf": [
                {
                    "title": "No parameters",
                    "description": "For histogram, dominator_tree, and leak_suspects.",
                    "type": "object",
                    "additionalProperties": False,
                },
                {
                    "title": "Path to GC roots",
                    "description": "For path_to_gc_roots.",
                    "type": "object",
                    "properties": {
                        "object_address": {
                            "type": "string",
                            "pattern": "^0x[0-9a-fA-F]+$",
                            "description": "MAT object address returned by a prior result.",
                        }
                    },
                    "required": ["object_address"],
                    "additionalProperties": False,
                },
                {
                    "title": "OQL",
                    "description": "For oql. A single SELECT expression only.",
                    "type": "object",
                    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 10000}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                {
                    "title": "List objects",
                    "description": "For list_objects.",
                    "type": "object",
                    "properties": {
                        "class_name": {
                            "type": "string",
                            "pattern": "^[A-Za-z_$][\\w$]*(?:\\.[A-Za-z_$][\\w$]*)*(?:\\[\\])?$",
                        },
                        "include_subclasses": {"type": "boolean", "default": False},
                    },
                    "required": ["class_name"],
                    "additionalProperties": False,
                },
            ]
        },
    ),
]


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
    async def close_heap_dump(heap_dump_id: str) -> dict[str, object]:
        """Stop processing and permanently delete a heap dump and its MAT data."""
        try:
            return await heap_dumps.close_heap_dump(heap_dump_id)
        except DomainError as error:
            raise_tool_error(error)

    @mcp.tool()
    async def run_mat_query(
        heap_dump_id: Annotated[str, Field(description="ID returned by open_heap_dump")],
        operation: Annotated[
            QueryOperation,
            Field(description="MAT operation. Select the matching data object variant."),
        ],
        data: QueryData,
    ) -> dict[str, object]:
        """Run a supported MAT query, report, or object listing."""
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
