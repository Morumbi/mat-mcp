from pathlib import Path
from types import SimpleNamespace
from typing import cast

from mat_mcp.db.repositories import HeapDumpRepository, MatQueryRepository
from mat_mcp.services.mat_query_service import MatQueryService


class CacheRepository:
    def __init__(self, dump: object, cached: object) -> None:
        self.dump = dump
        self.cached = cached
        self.records: list[object] = []

    async def find_by_id(self, _: str) -> object:
        return self.dump

    async def find_latest_completed(self, _: str, __: str) -> object:
        return self.cached

    async def add(self, query: object) -> None:
        self.records.append(query)


def test_dominator_tree_parser_normalizes_top_level_rows(tmp_path: Path) -> None:
    report = tmp_path / "Query_Command2.txt"
    report.write_text(
        "Class Name | Shallow Heap | Retained Heap | Percentage\n"
        "---------------------------------------------------------\n"
        "ApplicationImpl @ 0x800fe988 | 120 | 103,047,536 | 18.33%\n"
        "PathClassLoader @ 0x80d0c2b8 | 96 | 45,056,848 | 8.02%\n",
        encoding="utf-8",
    )
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        1,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    result = service._parse_dominator_tree(report)

    assert result["operation"] == "dominator_tree"
    assert result["metadata"] == {
        "total_rows": 2,
        "returned_rows": 1,
        "truncated": True,
        "execution_time_ms": None,
    }
    assert result["rows"] == [
        {
            "class_name": "ApplicationImpl",
            "object_id": None,
            "object_address": "0x800fe988",
            "parent_object_id": None,
            "depth": 0,
            "shallow_heap": 120,
            "retained_heap": 103047536,
        }
    ]


def test_path_to_gc_roots_parser_keeps_address_relationships(tmp_path: Path) -> None:
    report = tmp_path / "Query_Command2.txt"
    report.write_text(
        "Class Name | Shallow Heap | Retained Heap\n"
        "------------------------------------------\n"
        "ApplicationImpl @ 0x800fe988 | 120 | 103,047,536\n"
        "|- parent ProjectImpl @ 0x88080e60 | 96 | 380,992\n"
        "|  |- <Java Local> EventDispatchThread @ 0x800e0088 | 112 | 395,680\n"
        "|- myApplication ProgressIndicatorUtilService @ 0x8750d9b8 | 24 | 56\n",
        encoding="utf-8",
    )
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    result = service._parse_path_to_gc_roots(report)

    assert result["metadata"] == {
        "total_rows": 4,
        "returned_rows": 4,
        "truncated": False,
        "execution_time_ms": None,
    }
    assert result["rows"] == [
        {
            "class_name": "ApplicationImpl",
            "object_id": None,
            "object_address": "0x800fe988",
            "parent_object_id": None,
            "parent_object_address": None,
            "depth": 0,
            "shallow_heap": 120,
            "retained_heap": 103047536,
        },
        {
            "class_name": "parent ProjectImpl",
            "object_id": None,
            "object_address": "0x88080e60",
            "parent_object_id": None,
            "parent_object_address": "0x800fe988",
            "depth": 1,
            "shallow_heap": 96,
            "retained_heap": 380992,
        },
        {
            "class_name": "<Java Local> EventDispatchThread",
            "object_id": None,
            "object_address": "0x800e0088",
            "parent_object_id": None,
            "parent_object_address": "0x88080e60",
            "depth": 2,
            "shallow_heap": 112,
            "retained_heap": 395680,
        },
        {
            "class_name": "myApplication ProgressIndicatorUtilService",
            "object_id": None,
            "object_address": "0x8750d9b8",
            "parent_object_id": None,
            "parent_object_address": "0x800fe988",
            "depth": 1,
            "shallow_heap": 24,
            "retained_heap": 56,
        },
    ]


def test_path_to_gc_roots_uses_mat_path2gc_command(tmp_path: Path) -> None:
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    assert service._mat_command("path_to_gc_roots", {"object_address": "0x800fe988"}) == (
        "-command=path2gc 0x800fe988"
    )


def test_leak_suspects_parser_normalizes_mat_description(tmp_path: Path) -> None:
    pages = tmp_path / "report" / "pages"
    pages.mkdir(parents=True)
    (pages / "Description18.txt").write_text(
        'One instance of "com.example.Cache" loaded by "app.Loader @ 0x1" '
        "occupies 103,047,536 (18.33%) bytes. The retained objects need inspection.",
        encoding="utf-8",
    )
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    result = service._parse_leak_suspects(tmp_path / "report")

    assert result["operation"] == "leak_suspects"
    assert result["rows"] == [
        {
            "suspect_id": "suspect_1",
            "class_name": "com.example.Cache",
            "retained_heap": 103047536,
            "retained_percent": 18.33,
            "description": (
                'One instance of "com.example.Cache" loaded by "app.Loader @ 0x1" '
                "occupies 103,047,536 (18.33%) bytes. The retained objects need inspection."
            ),
        }
    ]


def test_leak_suspects_uses_standard_mat_report(tmp_path: Path) -> None:
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    assert service._mat_arguments("leak_suspects", {}) == [
        "-format=txt",
        "-unzip",
        "org.eclipse.mat.api:suspects",
    ]


def test_oql_parser_normalizes_object_identity_and_numbers(tmp_path: Path) -> None:
    report = tmp_path / "Query_Command2.txt"
    report.write_text(
        "Class Name | Shallow Heap | Retained Heap\n"
        "------------------------------------------\n"
        "java.lang.Runtime @ 0x802ec408 | 16 | 1,024\n"
        "Total: 1 entry | |\n",
        encoding="utf-8",
    )
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    result = service._parse_oql(report)

    assert result["columns"] == [
        {"name": "class_name", "type": "string"},
        {"name": "shallow_heap", "type": "integer"},
        {"name": "retained_heap", "type": "integer"},
    ]
    assert result["rows"] == [
        {
            "class_name": "java.lang.Runtime",
            "shallow_heap": 16,
            "retained_heap": 1024,
            "object_address": "0x802ec408",
            "object_id": None,
        }
    ]


def test_oql_uses_a_single_escaped_mat_command_argument(tmp_path: Path) -> None:
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    assert service._mat_command("oql", {"query": "SELECT * FROM java.lang.Runtime"}) == (
        '-command=oql \\"SELECT * FROM java.lang.Runtime\\"'
    )


def test_list_objects_generates_safe_oql_for_exact_class(tmp_path: Path) -> None:
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    assert service._mat_command("list_objects", {"class_name": "java.lang.String"}) == (
        '-command=oql \\"SELECT * FROM java.lang.String\\"'
    )
    assert service._mat_command(
        "list_objects", {"class_name": "java.lang.Number", "include_subclasses": True}
    ) == '-command=oql \\"SELECT * FROM INSTANCEOF java.lang.Number\\"'


def test_list_objects_parser_reuses_oql_normalization(tmp_path: Path) -> None:
    report = tmp_path / "Query_Command2.txt"
    report.write_text(
        "Class Name | Shallow Heap | Retained Heap\n"
        "------------------------------------------\n"
        "java.lang.Runtime @ 0x802ec408 | 16 | 16\n",
        encoding="utf-8",
    )
    service = MatQueryService(
        tmp_path / "ParseHeapDump.bat",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, object()),
        cast(MatQueryRepository, object()),
    )

    result = service._parse_list_objects(report)

    assert result["operation"] == "list_objects"
    assert result["rows"][0]["object_address"] == "0x802ec408"


async def test_completed_query_result_is_reused_from_cache(tmp_path: Path) -> None:
    workspace = tmp_path / "hd_cached"
    result_path = workspace / "queries" / "qry_source" / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        '{"operation":"histogram","columns":[],"rows":[],"metadata":'
        '{"total_rows":0,"returned_rows":0,"truncated":false,"execution_time_ms":123}}',
        encoding="utf-8",
    )
    dump = SimpleNamespace(heap_dump_id="hd_cached", status="ready", storage_path="hd_cached")
    source = SimpleNamespace(
        query_id="qry_source", result_path="hd_cached/queries/qry_source/result.json"
    )
    repository = CacheRepository(dump, source)
    service = MatQueryService(
        tmp_path / "missing-mat-executable",
        "1g",
        10,
        100,
        tmp_path,
        cast(HeapDumpRepository, repository),
        cast(MatQueryRepository, repository),
    )

    result = await service.run("hd_cached", "histogram", {})

    metadata = cast(dict[str, object], result["metadata"])
    assert metadata["total_rows"] == 0
    assert metadata["returned_rows"] == 0
    assert metadata["truncated"] is False
    assert metadata["cache_hit"] is True
    assert isinstance(metadata["execution_time_ms"], int)
    assert len(repository.records) == 1
    record = repository.records[0]
    assert record.cache_hit == 1
    assert record.cached_query_id == "qry_source"
    assert record.result_path == "hd_cached/queries/qry_source/result.json"
