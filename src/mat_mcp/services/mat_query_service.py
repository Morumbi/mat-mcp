"""MAT query adapter with normalized histogram and dominator-tree results."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import uuid4

from mat_mcp.db.models import HeapDump, MatQuery
from mat_mcp.db.repositories import HeapDumpRepository, MatQueryRepository
from mat_mcp.domain.errors import DomainError
from mat_mcp.services.indexing_service import utc_now


class MatQueryService:
    """Run supported MAT operations and persist their normalized results."""

    _PARSERS: dict[str, Callable[[MatQueryService, Path], dict[str, object]]] = {
        "histogram": lambda service, path: service._parse_histogram(path),
        "dominator_tree": lambda service, path: service._parse_dominator_tree(path),
        "path_to_gc_roots": lambda service, path: service._parse_path_to_gc_roots(path),
        "leak_suspects": lambda service, path: service._parse_leak_suspects(path),
    }

    def __init__(
        self,
        executable: Path,
        max_heap: str,
        timeout: int,
        max_rows: int,
        root: Path,
        dumps: HeapDumpRepository,
        queries: MatQueryRepository,
    ) -> None:
        self._executable, self._max_heap, self._timeout, self._max_rows = (
            executable.resolve(),
            max_heap,
            timeout,
            max_rows,
        )
        self._root, self._dumps, self._queries = root.resolve(), dumps, queries

    async def run(
        self, heap_dump_id: str, operation: str, data: dict[str, object]
    ) -> dict[str, object]:
        if operation not in self._PARSERS:
            raise DomainError(
                "invalid_input",
                "Only histogram, dominator_tree, and path_to_gc_roots are available.",
            )
        if operation in {"histogram", "dominator_tree", "leak_suspects"} and data:
            raise DomainError("invalid_input", f"{operation} requires an empty data object.")
        if operation == "path_to_gc_roots":
            address = data.get("object_address")
            if set(data) != {"object_address"} or not isinstance(address, str):
                raise DomainError(
                    "invalid_input",
                    "path_to_gc_roots requires only data.object_address.",
                )
            if re.fullmatch(r"0x[0-9a-fA-F]+", address) is None:
                raise DomainError(
                    "invalid_input", "data.object_address must be a hexadecimal MAT address."
                )
        dump = await self._dumps.find_by_id(heap_dump_id)
        if dump is None:
            raise DomainError("heap_dump_not_found", "Heap dump was not found.")
        if dump.status != "ready":
            raise DomainError(
                "heap_dump_not_ready", "Heap dump indexing is not complete.", retryable=True
            )
        return await self._execute(dump, operation, data)

    async def _execute(
        self, dump: HeapDump, operation: str, data: dict[str, object]
    ) -> dict[str, object]:
        query_id, started = f"qry_{uuid4().hex}", monotonic()
        workspace = self._root / dump.storage_path
        query_dir = workspace / "queries" / query_id
        await asyncio.to_thread(query_dir.mkdir, parents=True)
        request_path, stdout, stderr = (
            query_dir / "request.json",
            query_dir / "stdout.log",
            query_dir / "stderr.log",
        )
        request = {"heap_dump_id": dump.heap_dump_id, "operation": operation, "data": data}
        await asyncio.to_thread(
            request_path.write_text, json.dumps(request, separators=(",", ":")), "utf-8"
        )
        try:
            with stdout.open("wb") as out, stderr.open("wb") as err:
                process = await asyncio.create_subprocess_exec(
                    str(self._executable),
                    str(self._root / dump.hprof_path),
                    *self._mat_arguments(operation, data),
                    cwd=query_dir,
                    stdout=out,
                    stderr=err,
                    env={**os.environ, "JAVA_TOOL_OPTIONS": f"-Xmx{self._max_heap}"},
                )
                await asyncio.wait_for(process.wait(), self._timeout)
            if process.returncode != 0:
                raise DomainError("query_failed", f"MAT {operation} query failed.")
            raw_path = self._report_path(dump, operation)
            parser = self._PARSERS[operation]
            parsed = await asyncio.to_thread(parser, self, raw_path)
        except TimeoutError as error:
            raise DomainError(
                "query_failed", f"MAT {operation} query timed out.", retryable=True
            ) from error
        except OSError as error:
            raise DomainError(
                "query_failed", f"MAT {operation} query could not be started.", retryable=True
            ) from error

        metadata = cast(dict[str, object], parsed["metadata"])
        metadata["execution_time_ms"] = int((monotonic() - started) * 1000)
        result_path = query_dir / "result.json"
        await asyncio.to_thread(
            result_path.write_text, json.dumps(parsed, separators=(",", ":")), "utf-8"
        )
        now = utc_now()
        record = MatQuery(
            query_id=query_id,
            heap_dump_id=dump.heap_dump_id,
            operation=operation,
            request_data_json=json.dumps(data, separators=(",", ":")),
            request_hash=json.dumps(request, sort_keys=True, separators=(",", ":")),
            status="completed",
            cache_hit=0,
            query_directory_path=self._relative(query_dir),
            request_path=self._relative(request_path),
            stdout_path=self._relative(stdout),
            stderr_path=self._relative(stderr),
            raw_result_path=self._relative(raw_path),
            result_path=self._relative(result_path),
            total_rows=cast(int, metadata["total_rows"]),
            returned_rows=cast(int, metadata["returned_rows"]),
            truncated=int(cast(bool, metadata["truncated"])),
            duration_ms=cast(int, metadata["execution_time_ms"]),
            created_at=now,
            started_at=now,
            completed_at=now,
            updated_at=now,
        )
        await self._queries.add(record)
        return parsed

    def _mat_arguments(self, operation: str, data: dict[str, object]) -> list[str]:
        if operation == "leak_suspects":
            return ["-format=txt", "-unzip", "org.eclipse.mat.api:suspects"]
        return [self._mat_command(operation, data), "-format=txt", "-unzip", "org.eclipse.mat.api:query"]

    def _mat_command(self, operation: str, data: dict[str, object]) -> str:
        if operation == "path_to_gc_roots":
            return f"-command=path2gc {data['object_address']}"
        return f"-command={operation}"

    def _report_path(self, dump: HeapDump, operation: str) -> Path:
        report_root = (self._root / dump.hprof_path).parent
        if operation == "leak_suspects":
            return report_root / "heap_Leak_Suspects"
        return report_root / "heap_Query" / "pages" / "Query_Command2.txt"

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _parse_histogram(self, path: Path) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[2:]:
            match = re.match(r"^(.*?)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*$", line)
            if match is not None:
                rows.append(
                    {
                        "class_name": match.group(1).strip(),
                        "object_count": int(match.group(2).replace(",", "")),
                        "shallow_heap": int(match.group(3).replace(",", "")),
                        "retained_heap": None,
                        "object_id": None,
                        "object_address": None,
                    }
                )
        return self._tabular_result(
            "histogram",
            rows,
            [
                {"name": "class_name", "type": "string"},
                {"name": "object_count", "type": "integer"},
                {"name": "shallow_heap", "type": "integer", "unit": "bytes"},
            ],
        )

    def _parse_dominator_tree(self, path: Path) -> dict[str, object]:
        """Parse MAT's top-level dominator report without inventing child links."""
        rows: list[dict[str, object]] = []
        pattern = re.compile(
            r"^(.*?)\s*@\s*(0x[0-9a-fA-F]+)\s*\|\s*([\d,]+)\s*\|\s*"
            r"([\d,]+)\s*\|\s*[\d.,]+%\s*$"
        )
        for line in path.read_text(encoding="utf-8").splitlines()[2:]:
            match = pattern.match(line)
            if match is not None:
                rows.append(
                    {
                        "class_name": match.group(1).strip(),
                        "object_id": None,
                        "object_address": match.group(2),
                        "parent_object_id": None,
                        "depth": 0,
                        "shallow_heap": int(match.group(3).replace(",", "")),
                        "retained_heap": int(match.group(4).replace(",", "")),
                    }
                )
        return self._tabular_result(
            "dominator_tree",
            rows,
            [
                {"name": "class_name", "type": "string"},
                {"name": "object_address", "type": "string"},
                {"name": "parent_object_id", "type": "integer"},
                {"name": "depth", "type": "integer"},
                {"name": "shallow_heap", "type": "integer", "unit": "bytes"},
                {"name": "retained_heap", "type": "integer", "unit": "bytes"},
            ],
        )

    def _parse_path_to_gc_roots(self, path: Path) -> dict[str, object]:
        """Normalize MAT's indented path report, retaining address-based links."""
        rows: list[dict[str, object]] = []
        root_pattern = re.compile(
            r"^(.*?)\s*@\s*(0x[0-9a-fA-F]+)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*$"
        )
        child_pattern = re.compile(
            r"^(?P<indent>(?:\|\s{2}|\s{3})*)(?:\|-|'\-)\s*"
            r"(?P<label>.*?)\s*@\s*(?P<address>0x[0-9a-fA-F]+)\s*\|\s*"
            r"(?P<shallow>[\d,]+)\s*\|\s*(?P<retained>[\d,]+)\s*$"
        )
        ancestors: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines()[2:]:
            child = child_pattern.match(line)
            if child is not None:
                depth = 1 + len(re.findall(r"\|\s{2}|\s{3}", child.group("indent")))
                parent = ancestors[depth - 1] if len(ancestors) >= depth else None
                row = self._path_row(
                    child.group("label").strip(),
                    child.group("address"),
                    parent,
                    depth,
                    child.group("shallow"),
                    child.group("retained"),
                )
                rows.append(row)
                ancestors = ancestors[:depth]
                ancestors.append(child.group("address"))
                continue
            root = root_pattern.match(line)
            if root is not None:
                ancestors = [root.group(2)]
                rows.append(
                    self._path_row(
                        root.group(1).strip(), root.group(2), None, 0, root.group(3), root.group(4)
                    )
                )
        return self._tabular_result(
            "path_to_gc_roots",
            rows,
            [
                {"name": "class_name", "type": "string"},
                {"name": "object_address", "type": "string"},
                {"name": "parent_object_address", "type": "string"},
                {"name": "parent_object_id", "type": "integer"},
                {"name": "depth", "type": "integer"},
                {"name": "shallow_heap", "type": "integer", "unit": "bytes"},
                {"name": "retained_heap", "type": "integer", "unit": "bytes"},
            ],
        )

    def _parse_leak_suspects(self, report_dir: Path) -> dict[str, object]:
        """Extract one normalized row from every MAT problem-suspect description."""
        rows: list[dict[str, object]] = []
        for index, description_path in enumerate(
            sorted((report_dir / "pages").glob("Description*.txt")), start=1
        ):
            text = description_path.read_text(encoding="utf-8")
            summary = re.sub(r"\s+", " ", text).strip()
            class_match = re.search(r'One instance of "([^"]+)"', summary)
            heap_match = re.search(r"occupies ([\d,]+) \(([\d.]+)%\) bytes", summary)
            rows.append(
                {
                    "suspect_id": f"suspect_{index}",
                    "class_name": class_match.group(1) if class_match is not None else None,
                    "retained_heap": (
                        int(heap_match.group(1).replace(",", ""))
                        if heap_match is not None
                        else None
                    ),
                    "retained_percent": (
                        float(heap_match.group(2)) if heap_match is not None else None
                    ),
                    "description": summary,
                }
            )
        return self._tabular_result(
            "leak_suspects",
            rows,
            [
                {"name": "suspect_id", "type": "string"},
                {"name": "class_name", "type": "string"},
                {"name": "retained_heap", "type": "integer", "unit": "bytes"},
                {"name": "retained_percent", "type": "number", "unit": "percent"},
                {"name": "description", "type": "string"},
            ],
        )

    def _path_row(
        self,
        label: str,
        address: str,
        parent_address: str | None,
        depth: int,
        shallow: str,
        retained: str,
    ) -> dict[str, object]:
        return {
            "class_name": label,
            "object_id": None,
            "object_address": address,
            "parent_object_id": None,
            "parent_object_address": parent_address,
            "depth": depth,
            "shallow_heap": int(shallow.replace(",", "")),
            "retained_heap": int(retained.replace(",", "")),
        }

    def _tabular_result(
        self, operation: str, rows: list[dict[str, object]], columns: list[dict[str, str]]
    ) -> dict[str, object]:
        returned = rows[: self._max_rows]
        return {
            "operation": operation,
            "columns": columns,
            "rows": returned,
            "metadata": {
                "total_rows": len(rows),
                "returned_rows": len(returned),
                "truncated": len(rows) > len(returned),
                "execution_time_ms": None,
            },
        }
