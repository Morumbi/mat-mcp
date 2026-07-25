FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAT_MCP_CONFIG=/config/config.yaml

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY mat ./mat
COPY docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/storage /config /opt/mat \
    && cp -a /app/mat/linux/. /opt/mat/ \
    && chown -R appuser:appuser /app /data

USER appuser
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl --fail http://127.0.0.1:8000/health || exit 1
ENTRYPOINT ["/app/docker-entrypoint.sh"]
