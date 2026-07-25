from pathlib import Path

import pytest

from mat_mcp.config import load_settings


def write_config(path: Path) -> None:
    path.write_text(
        """
server: {host: 127.0.0.1, port: 8000}
storage: {root: /tmp/storage, database_path: /tmp/mat.db}
heap_dump: {max_size_bytes: 100, ttl_seconds: 60, ttl_cleanup_interval_seconds: 5}
mat:
  executable_path: /opt/mat/ParseHeapDump.sh
  max_heap: 1g
  index_timeout_seconds: 90
  query_timeout_seconds: 30
  max_parallel_queries_per_dump: 2
  max_result_rows: 100
sqlite: {busy_timeout_ms: 5000}
""",
        encoding="utf-8",
    )


def test_loads_yaml_configuration(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    write_config(config)

    settings = load_settings(config, {})

    assert settings.server.port == 8000
    assert settings.storage.database_path == Path("/tmp/mat.db").resolve()


def test_environment_overrides_yaml(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    write_config(config)

    settings = load_settings(config, {"MAT_MCP_SERVER__PORT": "8081"})

    assert settings.server.port == 8081


def test_relative_paths_are_resolved_from_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.yaml"
    write_config(config)
    config.write_text(
        config.read_text(encoding="utf-8")
        .replace("/tmp/storage", "./data/storage")
        .replace("/tmp/mat.db", "./data/mat.db")
        .replace("/opt/mat/ParseHeapDump.sh", "./mat/ParseHeapDump.sh"),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings(config, {})

    assert settings.storage.root == tmp_path / "data" / "storage"
    assert settings.storage.database_path == tmp_path / "data" / "mat.db"
    assert settings.mat.executable_path == tmp_path / "mat" / "ParseHeapDump.sh"


def test_invalid_configuration_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    write_config(config)

    with pytest.raises(ValueError, match="Invalid configuration"):
        load_settings(config, {"MAT_MCP_SERVER__PORT": "not-a-port"})
