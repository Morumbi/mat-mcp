FROM python:3.13-slim-trixie

ARG MAT_RELEASE=1.17.0
ARG MAT_VERSION=1.17.0.20260601

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAT_MCP_CONFIG=/config/config.yaml

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl openjdk-21-jre-headless unzip \
    && curl --fail --location --retry 3 \
        "https://download.eclipse.org/mat/${MAT_RELEASE}/rcp/MemoryAnalyzer-${MAT_VERSION}-linux.gtk.x86_64.zip" \
        --output /tmp/mat.zip \
    && mkdir -p /opt/mat \
    && unzip -q /tmp/mat.zip -d /tmp/mat \
    && cp -a /tmp/mat/mat/. /opt/mat/ \
    && rm -rf /tmp/mat /tmp/mat.zip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN chmod 0555 docker-entrypoint.sh \
    && uv sync --frozen --no-dev
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/storage /config /opt/mat \
    && chown -R appuser:appuser /app /data

USER appuser
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl --fail http://127.0.0.1:8000/health || exit 1
ENTRYPOINT ["/app/docker-entrypoint.sh"]
