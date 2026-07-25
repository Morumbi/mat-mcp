from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mat_mcp.domain.errors import DomainError
from mat_mcp.storage.filesystem import FileStorage


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def test_hprof_upload_is_validated_and_prepared(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, 1024)
    upload = await storage.store_upload("heap.hprof", chunks(b"JAVA PROFILE 1.0.2\x00payload"))

    prepared = await storage.prepare_dump(upload.upload_id, "hd_test")

    assert prepared.original_type == "hprof"
    assert prepared.hprof_path.exists()
    assert prepared.content_sha256


async def test_invalid_hprof_is_rejected(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path, 1024)
    upload = await storage.store_upload("heap.hprof", chunks(b"not a dump"))

    with pytest.raises(DomainError, match="valid HPROF"):
        await storage.prepare_dump(upload.upload_id, "hd_test")
