"""Application bootstrap and graceful HTTP-server lifecycle."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from starlette.applications import Starlette

from mat_mcp.api.app import create_asgi_app, create_mcp_server
from mat_mcp.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from mat_mcp.db.engine import create_database_engine, create_session_factory
from mat_mcp.db.repositories import HeapDumpRepository, MatQueryRepository
from mat_mcp.logging import configure_logging
from mat_mcp.services.heap_dump_service import HeapDumpService
from mat_mcp.services.indexing_service import IndexingService
from mat_mcp.services.mat_query_service import MatQueryService
from mat_mcp.storage.filesystem import FileStorage


def run_migrations(database_path: Path) -> None:
    """Upgrade the configured SQLite database before serving MCP requests."""
    root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(root / "alembic.ini"))
    alembic_config.set_main_option(
        "sqlalchemy.url", f"sqlite:///{database_path.resolve().as_posix()}"
    )
    command.upgrade(alembic_config, "head")


def create_application(settings: Settings) -> Starlette:
    """Build the ASGI app after startup validation and migrations."""
    engine = create_database_engine(settings.storage.database_path, settings.sqlite.busy_timeout_ms)
    repository = HeapDumpRepository(create_session_factory(engine))
    query_repository = MatQueryRepository(create_session_factory(engine))
    storage = FileStorage(settings.storage.root, settings.heap_dump.max_size_bytes)
    indexer = IndexingService(
        settings.mat.executable_path,
        settings.mat.max_heap,
        settings.mat.index_timeout_seconds,
        repository,
    )
    heap_dumps = HeapDumpService(storage, repository, indexer, settings.heap_dump.ttl_seconds)
    queries = MatQueryService(
        settings.mat.executable_path,
        settings.mat.max_heap,
        settings.mat.query_timeout_seconds,
        settings.mat.max_result_rows,
        settings.storage.root,
        repository,
        query_repository,
    )
    return create_asgi_app(create_mcp_server(heap_dumps, queries), storage)


def main() -> None:
    """Start the Streamable HTTP MCP server or exit nonzero on startup failure."""
    logger = configure_logging()
    config_path = Path(os.environ.get("MAT_MCP_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        settings = load_settings(config_path)
        logger.info("Starting MAT MCP application")
        logger.info("Loaded configuration from %s", config_path)
        settings.storage.database_path.parent.mkdir(parents=True, exist_ok=True)
        settings.storage.root.mkdir(parents=True, exist_ok=True)
        logger.info("Applying Alembic migrations")
        run_migrations(settings.storage.database_path)
        logger.info("FastMCP Streamable HTTP is available at /mcp")
        uvicorn.run(
            create_application(settings),
            host=settings.server.host,
            port=settings.server.port,
            log_config=None,
        )
        logger.info("MAT MCP application stopped")
    except Exception:
        logger.critical("MAT MCP startup failed", exc_info=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
