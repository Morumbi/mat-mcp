# MAT MCP

Runnable Milestone 1 skeleton for a Streamable HTTP MCP server around Eclipse MAT.

## Development

```bash
uv sync
uv run alembic upgrade head
uv run python -m mat_mcp.main
```

The default configuration is `config/config.example.yaml`. Set `MAT_MCP_CONFIG` to use
another YAML file. Nested environment overrides use `MAT_MCP_` and double underscores,
for example `MAT_MCP_SERVER__PORT=8080`.

The MCP endpoint is `/mcp`; health is available at `/health`.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```
