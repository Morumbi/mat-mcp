"""HTTP upload endpoint used before the MCP open operation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse

from mat_mcp.domain.errors import DomainError
from mat_mcp.storage.filesystem import FileStorage


def create_upload_endpoint(
    storage: FileStorage,
) -> Callable[[Request], Awaitable[JSONResponse]]:
    """Create a streaming POST handler bound to the configured storage."""

    async def upload(request: Request) -> JSONResponse:
        filename = request.headers.get("x-filename")
        if filename is None:
            error = DomainError("invalid_input", "X-Filename header is required.")
            return JSONResponse(error.as_response(), status_code=400)
        try:
            stored = await storage.store_upload(filename, request.stream())
        except DomainError as error:
            return JSONResponse(error.as_response(), status_code=400)
        return JSONResponse(
            {"upload_id": stored.upload_id, "filename": stored.filename, "size": stored.size},
            status_code=201,
        )

    return upload
