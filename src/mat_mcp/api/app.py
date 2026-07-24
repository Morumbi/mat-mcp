"""ASGI composition for Streamable HTTP MCP and health."""

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from mat_mcp.api.health import health


def create_mcp_server() -> FastMCP:
    """Create the empty MCP server; MAT tools arrive in later milestones."""
    return FastMCP("MAT MCP")


def create_asgi_app(mcp: FastMCP) -> Starlette:
    """Expose only Streamable HTTP MCP plus the liveness endpoint."""
    mcp_app = mcp.http_app(path="/mcp")
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=mcp_app)],
        lifespan=mcp_app.lifespan,
    )
