from pathlib import Path
from typing import cast

from mat_mcp.db.repositories import HeapDumpRepository, MatQueryRepository
from mat_mcp.services.mat_query_service import MatQueryService


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
