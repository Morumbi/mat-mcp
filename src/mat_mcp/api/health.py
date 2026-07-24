"""Health endpoint implementation."""

from starlette.requests import Request
from starlette.responses import JSONResponse


async def health(_: Request) -> JSONResponse:
    """Report only that the web process is serving requests."""
    return JSONResponse({"status": "ok"})
