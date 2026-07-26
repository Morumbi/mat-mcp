# MAT MCP

`mat-mcp` is a Streamable HTTP MCP service for analyzing Java heap dumps with
[Eclipse Memory Analyzer (MAT)](https://eclipse.dev/mat/). It accepts HPROF files,
runs MAT indexing in the background, and stores work files and metadata locally.

## Features

- Streaming HTTP upload of `.hprof`, `.zip`, and `.gz` files.
- Asynchronous preparation and indexing: `open_heap_dump` returns an ID immediately.
- Idempotent opening: the same `upload_id` returns the same `heap_dump_id`, including
  after a server restart, while the dump remains open and has not expired.
- Indexing and query status reporting, result retrieval, and explicit deletion through MCP.
- MAT operations: `histogram`, `dominator_tree`, `path_to_gc_roots`, `leak_suspects`,
  `oql`, and `list_objects`.
- Asynchronous MAT queries with per-dump concurrency limits, a cache for identical completed
  queries, and TTL cleanup.
- Hard response limits: at most 50 rows and 256 KiB of JSON. Rows are never split; if
  the next complete row does not fit, it is omitted from the result.

## Requirements

- Python 3.13.
- Java 21+.
- [Eclipse MAT](https://eclipse.dev/mat/)
- Sufficient free disk space: while a plain HPROF is being prepared, both the source
  file and a MAT working copy are stored temporarily.

## Run locally

```bash
uv sync
uv run python -m mat_mcp.main
```

Alembic migrations are applied automatically at startup. By default, the service is
available at `http://127.0.0.1:8000`: MCP is served at `/mcp` and the health endpoint
is `/health`.

Settings are in `config/config.yaml`. Set `MAT_MCP_CONFIG` to use a different
file. Nested settings can be overridden with environment variables such as
`MAT_MCP_SERVER__PORT=8080`.

### Environment variables

Every setting from `config/config.yaml` can be overridden without changing the
file. Use the `MAT_MCP_` prefix and separate nested keys with two underscores
(`__`). Values are parsed as YAML, so numeric values do not need quotes.

| Configuration key                        | Environment variable                              | Description                                                                         |
|------------------------------------------|---------------------------------------------------|-------------------------------------------------------------------------------------|
| Config file path                         | `MAT_MCP_CONFIG`                                  | Path to the YAML configuration file. Defaults to `config/config.yaml`.              |
| `server.host`                            | `MAT_MCP_SERVER__HOST`                            | Network interface on which the HTTP server listens.                                 |
| `server.port`                            | `MAT_MCP_SERVER__PORT`                            | TCP port for the HTTP server (1–65535).                                             |
| `storage.root`                           | `MAT_MCP_STORAGE__ROOT`                           | Root directory for uploaded files and per-dump workspaces.                          |
| `storage.database_path`                  | `MAT_MCP_STORAGE__DATABASE_PATH`                  | Path to the SQLite database that stores dump and query metadata.                    |
| `heap_dump.max_size_bytes`               | `MAT_MCP_HEAP_DUMP__MAX_SIZE_BYTES`               | Maximum accepted upload size in bytes.                                              |
| `heap_dump.ttl_seconds`                  | `MAT_MCP_HEAP_DUMP__TTL_SECONDS`                  | How long an inactive heap dump and its workspace are retained, in seconds.          |
| `heap_dump.ttl_cleanup_interval_seconds` | `MAT_MCP_HEAP_DUMP__TTL_CLEANUP_INTERVAL_SECONDS` | Interval, in seconds, between expired-dump cleanup runs.                            |
| `mat.executable_path`                    | `MAT_MCP_MAT__EXECUTABLE_PATH`                    | Path to the MAT launcher; `/opt/mat/ParseHeapDump.sh` in the Docker image.          |
| `mat.max_heap`                           | `MAT_MCP_MAT__MAX_HEAP`                           | Maximum Java heap passed to each MAT process, for example `8g`.                     |
| `mat.index_timeout_seconds`              | `MAT_MCP_MAT__INDEX_TIMEOUT_SECONDS`              | Maximum duration of initial MAT indexing, in seconds.                               |
| `mat.query_timeout_seconds`              | `MAT_MCP_MAT__QUERY_TIMEOUT_SECONDS`              | Maximum duration of one MAT query, in seconds.                                      |
| `mat.max_parallel_queries_per_dump`      | `MAT_MCP_MAT__MAX_PARALLEL_QUERIES_PER_DUMP`      | Maximum MAT queries allowed concurrently for one heap dump.                         |
| `mat.max_result_rows`                    | `MAT_MCP_MAT__MAX_RESULT_ROWS`                    | Maximum rows returned for one query; from 1 to 50.                                  |
| `mat.max_result_bytes`                   | `MAT_MCP_MAT__MAX_RESULT_BYTES`                   | Maximum UTF-8 JSON result size in bytes; from 1,024 to 262,144.                     |
| `sqlite.busy_timeout_ms`                 | `MAT_MCP_SQLITE__BUSY_TIMEOUT_MS`                 | Time SQLite waits for a locked database before returning an error, in milliseconds. |

For the Docker image, point the service at the MAT executable installed in the
image:

```bash
docker run --rm -p 8000:8000 \
  -e MAT_MCP_MAT__EXECUTABLE_PATH=/opt/mat/ParseHeapDump.sh \
  -v "$PWD/config/config.yaml:/config/config.yaml:ro" \
  -v mat-mcp-data:/data \
  mat-mcp
```

## Typical workflow

1. Upload a file with `POST /uploads`, passing the file name in the `X-Filename` header:

   ```bash
   curl -X POST http://127.0.0.1:8000/uploads \
     -H 'X-Filename: heap.hprof' \
     --data-binary '@/path/to/heap.hprof'
   ```

   The response contains `upload_id`.

2. Call the `open_heap_dump` MCP tool with that `upload_id`. It immediately returns a
   `heap_dump_id` with the `indexing` status. During the first phase,
   `get_heap_dump_status` reports `Preparing heap dump`.

3. Poll `get_heap_dump_status` until the status is `ready`. A `failed` response contains
   the error details. Repeating `open_heap_dump` with the same `upload_id` returns the
   same ID. After `close_heap_dump` or TTL cleanup, the key is no longer valid and the
   file must be uploaded again.

4. Call `run_mat_query` for a ready dump. It submits work immediately and returns a query ID:

   ```json
   {
     "query_id": "qry_01J...",
     "status": "queued",
     "cache_hit": false
   }
   ```

5. Poll `get_mat_query_status` with the returned `query_id`. The status moves from
   `queued` to `running` and then to `completed` or `failed`. Poll after 1--2 seconds
   initially, then no more often than every 5 seconds. A failed query includes a stable error
   code, message, and whether retrying is appropriate.

6. When the status is `completed`, call `get_mat_query_result` with the same `query_id` to
   receive the normalized `columns`, `rows`, and `metadata`. Calling it while the query is
   queued or running returns the retryable `query_not_ready` error.

### `run_mat_query` parameters

| `operation`        | `data`                                                         |
|--------------------|----------------------------------------------------------------|
| `histogram`        | `{}`                                                           |
| `dominator_tree`   | `{}`                                                           |
| `leak_suspects`    | `{}`                                                           |
| `path_to_gc_roots` | `{"object_address":"0x..."}`                                   |
| `oql`              | `{"query":"SELECT ..."}` — one line, one `SELECT`              |
| `list_objects`     | `{"class_name":"java.lang.String","include_subclasses":false}` |

For `path_to_gc_roots`, use an `object_address` from a previous MAT result, not a
numeric `object_id`.

## Query lifecycle

All MAT operations use the same asynchronous lifecycle:

```text
run_mat_query -> queued -> running -> completed -> get_mat_query_result
                                      |
                                      +-> failed
```

`get_mat_query_status` is available in every state. If an identical request has already
completed for the same heap dump, `run_mat_query` returns that existing query ID with
`cache_hit: true`; no new MAT process is started. If the same request is already queued or
running, it returns the active query ID instead of starting duplicate work.

## Result limits

The `mat` configuration section provides these controls:

- `max_result_rows`: 1 to 50, default 50.
- `max_result_bytes`: 1,024 to 262,144, default 262,144.
- `max_parallel_queries_per_dump`: query parallelism for a single dump.
- `index_timeout_seconds` and `query_timeout_seconds`: MAT timeouts.

## OpenCode

OpenCode connects to this service as a remote Streamable HTTP MCP server. Create
`opencode.json` in the OpenCode project (or add the same block to the global
`~/.config/opencode/opencode.json`) with the following configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "mat": {
        "type": "remote",
        "url": "http://127.0.0.1:8000/mcp",
        "oauth": false,
        "codemode": false,
        "enabled": true
      }
    }
  }
}
```

Start `mat-mcp` first, then launch OpenCode from the project directory. Verify the
connection with:

```bash
opencode2 mcp list
```

The `mat` server is local and has no authentication in the default configuration;
do not expose it outside a trusted network without adding access control. OpenCode
prefixes its MCP tools with the server name, for example `mat_run_mat_query`.
See the [OpenCode MCP server documentation](https://opencode.ai/v2/docs/mcp-servers)
and [configuration reference](https://opencode.ai/docs/config) for remote-server and
global-configuration options.

## Docker

The Linux image downloads Eclipse MAT 1.17.0 during the build and includes Java 21.
Mount configuration and persistent data:

```bash
docker build -t mat-mcp .
docker run --rm -p 8000:8000 \
  -e MAT_MCP_MAT__EXECUTABLE_PATH=/opt/mat/ParseHeapDump.sh \
  -v "$PWD/config/config.yaml:/config/config.yaml:ro" \
  -v mat-mcp-data:/data \
  mat-mcp
```

## Checks

```bash
uv run ruff check src tests migrations
uv run mypy src
uv run pytest --cov-report=xml:coverage.xml
```
