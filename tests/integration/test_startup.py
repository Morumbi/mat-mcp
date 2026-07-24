from pathlib import Path

import pytest

import mat_mcp.main as application_main


def test_startup_stops_when_migration_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
server: {{host: 127.0.0.1, port: 8000}}
storage: {{root: {tmp_path.as_posix()}/storage, database_path: {tmp_path.as_posix()}/metadata.db}}
heap_dump: {{max_size_bytes: 1, ttl_seconds: 1, ttl_cleanup_interval_seconds: 1}}
mat:
  executable_path: /opt/mat/ParseHeapDump.sh
  max_heap: 1g
  index_timeout_seconds: 1
  query_timeout_seconds: 1
  max_parallel_queries_per_dump: 1
  max_result_rows: 1
sqlite: {{busy_timeout_ms: 0}}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAT_MCP_CONFIG", str(config))
    monkeypatch.setattr(
        application_main, "run_migrations", lambda _: (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr(application_main.uvicorn, "run", lambda **_: pytest.fail("server started"))

    with pytest.raises(SystemExit, match="1"):
        application_main.main()
