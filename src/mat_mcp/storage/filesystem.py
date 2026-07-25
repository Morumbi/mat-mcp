"""Safe streaming upload and per-dump filesystem workspace management."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import shutil
import zipfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol
from uuid import uuid4

from mat_mcp.domain.errors import DomainError

HPROF_HEADER = b"JAVA PROFILE"
ALLOWED_SUFFIXES = {".hprof": "hprof", ".zip": "zip", ".gz": "gz"}


@dataclass(frozen=True, slots=True)
class Upload:
    """In-memory metadata for a one-time upload."""

    upload_id: str
    filename: str
    path: Path
    size: int


@dataclass(frozen=True, slots=True)
class PreparedDump:
    """Validated, extracted data ready to be persisted and indexed."""

    filename: str
    original_type: str
    source_size: int
    uncompressed_size: int
    content_sha256: str
    workspace: Path
    hprof_path: Path


class BinaryStream(Protocol):
    """Minimal interface shared by compressed and regular binary streams."""

    def read(self, size: int = -1) -> bytes: ...


class BinarySink(Protocol):
    """Minimal binary output interface."""

    def write(self, data: bytes) -> int: ...


class FileStorage:
    """Owns temporary uploads and isolated heap-dump workspaces."""

    def __init__(self, root: Path, max_size_bytes: int) -> None:
        self._root = root.resolve()
        self._uploads = self._root / "uploads"
        self._max_size = max_size_bytes
        self._pending: dict[str, Upload] = {}

    async def store_upload(self, filename: str, chunks: AsyncIterable[bytes]) -> Upload:
        """Stream an HTTP request body to a one-time temporary upload file."""
        safe_name, _ = self._filename_and_type(filename)
        await asyncio.to_thread(self._uploads.mkdir, parents=True, exist_ok=True)
        upload_id = f"upl_{uuid4().hex}"
        path = self._uploads / upload_id
        size = 0
        try:
            with path.open("xb") as output:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self._max_size:
                        raise DomainError(
                            "file_too_large", "Upload exceeds the configured size limit."
                        )
                    await asyncio.to_thread(output.write, chunk)
        except Exception:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        upload = Upload(upload_id, safe_name, path, size)
        self._pending[upload_id] = upload
        return upload

    async def prepare_dump(self, upload_id: str, heap_dump_id: str) -> PreparedDump:
        """Consume, validate, and unpack an uploaded heap dump into its workspace."""
        upload = self._pending.pop(upload_id, None)
        if upload is None:
            raise DomainError("invalid_input", "Upload was not found or has already been consumed.")
        workspace = self._root / heap_dump_id
        try:
            return await asyncio.to_thread(self._prepare_dump_sync, upload, workspace)
        finally:
            await asyncio.to_thread(upload.path.unlink, missing_ok=True)

    def remove_workspace(self, workspace: Path) -> None:
        """Remove a generated workspace only; caller supplies an internal path."""
        resolved = workspace.resolve()
        if resolved.parent != self._root:
            raise ValueError("Workspace must be a direct child of storage root.")
        try:
            shutil.rmtree(resolved)
        except FileNotFoundError:
            return

    def workspace_for(self, storage_path: str) -> Path:
        """Resolve a database workspace path without allowing traversal outside storage."""
        workspace = (self._root / storage_path).resolve()
        if workspace.parent != self._root:
            raise ValueError("Stored workspace path is outside storage root.")
        return workspace

    def _prepare_dump_sync(self, upload: Upload, workspace: Path) -> PreparedDump:
        _, original_type = self._filename_and_type(upload.filename)
        source = workspace / "source" / upload.filename
        hprof_path = workspace / "heap" / "heap.hprof"
        index_path = workspace / "indexes"
        workspace.mkdir(parents=True, exist_ok=False)
        try:
            source.parent.mkdir()
            hprof_path.parent.mkdir()
            index_path.mkdir()
            shutil.move(str(upload.path), source)
            if original_type == "hprof":
                shutil.copyfile(source, hprof_path)
            elif original_type == "gz":
                with gzip.open(source, "rb") as compressed, hprof_path.open("wb") as output:
                    self._copy_limited(compressed, output)
            else:
                with zipfile.ZipFile(source) as archive:
                    entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                    if len(entries) != 1 or len(archive.infolist()) != 1:
                        raise DomainError(
                            "invalid_input", "ZIP archive must contain exactly one file."
                        )
                    entry = entries[0]
                    if (
                        entry.is_dir()
                        or entry.filename.endswith("/")
                        or entry.file_size > self._max_size
                    ):
                        raise DomainError(
                            "invalid_input", "ZIP archive contains an invalid heap dump."
                        )
                    with archive.open(entry) as compressed, hprof_path.open("wb") as output:
                        self._copy_limited(compressed, output)
            size, digest = self._validate_hprof(hprof_path)
            return PreparedDump(
                upload.filename, original_type, upload.size, size, digest, workspace, hprof_path
            )
        except Exception:
            self.remove_workspace(workspace)
            raise

    def _copy_limited(self, source: BinaryStream, output: BinarySink) -> None:
        total = 0
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > self._max_size:
                raise DomainError(
                    "file_too_large", "Uncompressed heap dump exceeds the configured size limit."
                )
            output.write(chunk)

    def _validate_hprof(self, path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        with path.open("rb") as heap_dump:
            header = heap_dump.read(len(HPROF_HEADER))
            if header != HPROF_HEADER:
                raise DomainError("invalid_hprof", "Uploaded content is not a valid HPROF file.")
            digest.update(header)
            for chunk in iter(lambda: heap_dump.read(1024 * 1024), b""):
                digest.update(chunk)
        return path.stat().st_size, digest.hexdigest()

    @staticmethod
    def _filename_and_type(filename: str) -> tuple[str, str]:
        safe_name = PurePath(filename).name
        suffix = Path(safe_name).suffix.lower()
        original_type = ALLOWED_SUFFIXES.get(suffix)
        if not safe_name or original_type is None:
            raise DomainError(
                "unsupported_file_type", "Only .hprof, .zip, and .gz uploads are supported."
            )
        return safe_name, original_type
