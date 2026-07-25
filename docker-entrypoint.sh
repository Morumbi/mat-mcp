#!/bin/sh
set -eu

/app/.venv/bin/alembic upgrade head
exec /app/.venv/bin/python -m mat_mcp.main
