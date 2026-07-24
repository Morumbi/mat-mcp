from fastmcp import FastMCP
from starlette.testclient import TestClient

from mat_mcp.api.app import create_asgi_app, create_mcp_server


def test_health_reports_process_liveness() -> None:
    app = create_asgi_app(create_mcp_server())

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fastmcp_server_is_created() -> None:
    assert isinstance(create_mcp_server(), FastMCP)
