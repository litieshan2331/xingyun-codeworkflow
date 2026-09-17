"""阶段一开发数据集完整性测试。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts.score_retrieval import index_chunk_parents, index_dataset, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "retrieval.v1.jsonl"
INVENTORY_PATH = ROOT / "datasets" / "chunks.v1.jsonl"


def test_development_dataset_has_120_ordered_single_kb_cases() -> None:
    """开发集按单知识库路由顺序包含 120 个案例。"""

    cases = index_dataset(read_jsonl(DATASET_PATH))

    assert len(cases) == 120
    assert len({case["query"] for case in cases.values()}) == 120
    assert Counter(case["knowledge_base"] for case in cases.values()) == {
        "form": 30,
        "list": 30,
        "js": 60,
    }
    assert Counter(case["route_group"] for case in cases.values()) == {
        "form-single": 30,
        "list-single": 30,
        "js-single": 60,
    }
    assert Counter(
        case["query_type"]
        for case in cases.values()
        if case["route_group"] == "js-single"
    ) == {
        "state_props": 5,
        "form_callback": 10,
        "flow_callback": 10,
        "tool": 5,
        "module_js": 5,
        "boundary": 5,
        "multi_hop": 20,
    }
    assert [case["route_group"] for case in cases.values()] == (
        ["form-single"] * 30 + ["list-single"] * 30 + ["js-single"] * 60
    )
    assert {tuple(case["search_knowledge_bases"]) for case in cases.values()} == {
        ("form",), ("list",), ("js",)
    }
    assert all(
        len(case["reference_context_ids"]) >= 3
        for case in cases.values()
        if case["query_type"] == "multi_hop"
    )


def test_every_reference_child_chunk_exists_in_its_declared_knowledge_base() -> None:
    """每个参考子 chunk 都存在于清单中，且属于案例声明的知识库。"""

    cases = index_dataset(read_jsonl(DATASET_PATH))
    inventory_rows = read_jsonl(INVENTORY_PATH)
    inventory = {str(row["chunk_id"]): row for row in inventory_rows}
    parents = index_chunk_parents(inventory_rows)

    for case in cases.values():
        for chunk_id in case["reference_context_ids"]:
            assert chunk_id in inventory, f"{case['case_id']} 引用了不存在的 chunk：{chunk_id}"
            assert inventory[chunk_id]["knowledge_base"] in case["target_knowledge_bases"]
            assert chunk_id in parents
