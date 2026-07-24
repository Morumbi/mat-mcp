"""Validated application configuration loaded from YAML and environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ENV_PREFIX = "MAT_MCP_"
DEFAULT_CONFIG_PATH = Path("config/config.example.yaml")


class ServerSettings(BaseModel):
    """HTTP server settings."""

    model_config = ConfigDict(extra="forbid")
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class StorageSettings(BaseModel):
    """Persistent storage locations."""

    model_config = ConfigDict(extra="forbid")
    root: Path
    database_path: Path


class HeapDumpSettings(BaseModel):
    """Heap-dump retention and upload limits."""

    model_config = ConfigDict(extra="forbid")
    max_size_bytes: int = Field(gt=0)
    ttl_seconds: int = Field(gt=0)
    ttl_cleanup_interval_seconds: int = Field(gt=0)


class MatSettings(BaseModel):
    """Eclipse MAT process settings."""

    model_config = ConfigDict(extra="forbid")
    executable_path: Path
    max_heap: str = Field(min_length=1)
    index_timeout_seconds: int = Field(gt=0)
    query_timeout_seconds: int = Field(gt=0)
    max_parallel_queries_per_dump: int = Field(gt=0)
    max_result_rows: int = Field(gt=0)


class SqliteSettings(BaseModel):
    """SQLite driver settings."""

    model_config = ConfigDict(extra="forbid")
    busy_timeout_ms: int = Field(ge=0)


class Settings(BaseModel):
    """All runtime settings."""

    model_config = ConfigDict(extra="forbid")
    server: ServerSettings
    storage: StorageSettings
    heap_dump: HeapDumpSettings
    mat: MatSettings
    sqlite: SqliteSettings

    @field_validator("storage")
    @classmethod
    def database_has_parent(cls, storage: StorageSettings) -> StorageSettings:
        if storage.database_path.name == "":
            raise ValueError("database_path must name a SQLite file")
        return storage


def _parse_environment_value(value: str) -> Any:
    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return value


def _apply_environment_overrides(data: dict[str, Any], environ: dict[str, str]) -> None:
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX) or name == "MAT_MCP_CONFIG":
            continue
        path = name.removeprefix(ENV_PREFIX).lower().split("__")
        if any(not part for part in path):
            continue
        target = data
        for part in path[:-1]:
            existing = target.get(part)
            if not isinstance(existing, dict):
                target[part] = {}
            target = target[part]
        target[path[-1]] = _parse_environment_value(value)


def load_settings(
    config_path: Path | None = None, environ: dict[str, str] | None = None
) -> Settings:
    """Load YAML settings and apply ``MAT_MCP_*`` nested environment overrides."""
    environment = dict(os.environ) if environ is None else environ
    path = config_path or Path(environment.get("MAT_MCP_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Unable to read configuration file: {path}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML configuration: {path}") from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping")
    _apply_environment_overrides(raw, environment)
    try:
        return Settings.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"Invalid configuration: {error}") from error
