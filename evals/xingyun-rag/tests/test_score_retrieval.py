"""阶段一 chunk Recall 和 Precision 评分单元测试。"""

from __future__ import annotations

import pytest

from scripts.score_retrieval import (
    InputError,
    build_report,
    index_chunk_parents,
    index_dataset,
    index_run,
    score_case,
)


CHUNK_PARENTS = {
    "a": "parent-a",
    "b": "parent-b",
    "c": "parent-b",
    "d": "parent-d",
}


def dataset_case(
    case_id: str,
    knowledge_base: str,
    references: list[str],
) -> dict[str, object]:
    """构造一个紧凑的已标注案例 fixture。"""

    return {
        "case_id": case_id,
        "knowledge_base": knowledge_base,
        "query": "检索问题",
        "reference_context_ids": references,
    }


def run_case(
    case_id: str,
    retrieved: list[str],
    *,
    status: str = "completed",
    error: str | None = None,
    parent_chunk_id: str | None = None,
) -> dict[str, object]:
    """构造一个紧凑的结构化检索运行 fixture。"""

    return {
        "case_id": case_id,
        "retrieval_hits": [
            {
                "retrieval_hit_id": chunk_id,
                "retrieved_context": f"context for {chunk_id}",
                "parent_chunk_id": parent_chunk_id,
            }
            for chunk_id in retrieved
        ],
        "status": status,
        "error": error,
    }


def test_score_case_reports_hits_missing_and_unexpected_ids() -> None:
    score = score_case(
        dataset_case("form-001", "form", ["a", "b"]),
        run_case("form-001", ["a", "x", "x"]),
        CHUNK_PARENTS,
    )

    assert score["scored"] is True
    assert score["recall"] == 0.5
    assert score["precision"] == 0.0
    assert score["parent_precision"] == 0.5
    assert score["hit_context_ids"] == ["a"]
    assert score["missing_context_ids"] == ["b"]
    assert score["unexpected_context_ids"] == ["x"]
    assert score["retrieval_hit_ids"] == ["a", "x"]


def test_score_case_assigns_zero_precision_and_recall_to_completed_empty_retrieval() -> None:
    score = score_case(
        dataset_case("form-001", "form", ["a"]),
        run_case("form-001", []),
        CHUNK_PARENTS,
    )

    assert score["scored"] is True
    assert score["recall"] == 0.0
    assert score["precision"] == 0.0


def test_score_case_uses_candidates_for_recall_and_final_parents_for_precision() -> None:
    case = dataset_case("form-001", "form", ["a"])
    run = index_run(
        [
            {
                "case_id": "form-001",
                "candidate_retrieval_hits": [
                    {
                        "retrieval_hit_id": "a",
                        "retrieved_context": "candidate",
                        "parent_chunk_id": "parent-a",
                    },
                    {
                        "retrieval_hit_id": "b",
                        "retrieved_context": "candidate",
                        "parent_chunk_id": "parent-b",
                    },
                ],
                "final_retrieval_hits": [
                    {
                        "retrieval_hit_id": "a",
                        "retrieved_context": "final parent context",
                        "parent_chunk_id": "parent-a",
                    }
                ],
                "retrieval_hits": [],
                "status": "completed",
                "error": None,
            }
        ]
    )["form-001"]

    score = score_case(case, run, CHUNK_PARENTS)

    assert score["candidate_recall"] == 1.0
    assert score["candidate_parent_recall"] == 1.0
    assert score["final_parent_precision"] == 1.0


def test_score_case_keeps_failed_runs_unscored() -> None:
    score = score_case(
        dataset_case("js-001", "js", ["a"]),
        run_case("js-001", [], status="failed", error="timeout"),
        CHUNK_PARENTS,
    )

    assert score == {
        "case_id": "js-001",
        "knowledge_base": "js",
        "search_knowledge_bases": ["js"],
        "target_knowledge_bases": ["js"],
        "status": "failed",
        "reference_context_ids": ["a"],
        "retrieval_hit_ids": [],
        "candidate_retrieval_hit_ids": [],
        "final_retrieval_hit_ids": [],
        "reference_parent_context_ids": ["parent-a"],
        "candidate_parent_context_ids": [],
        "final_parent_context_ids": [],
        "retrieval_parent_context_ids": [],
        "retrieval_hit_audit": [],
        "scored": False,
        "unscored_reason": "timeout",
    }


def test_build_report_uses_macro_averages_and_knowledge_base_groups() -> None:
    report = build_report(
        index_dataset(
            [
                dataset_case("form-001", "form", ["a"]),
                dataset_case("form-002", "form", ["b", "c"]),
                dataset_case("list-001", "list", ["d"]),
            ]
        ),
        index_run(
            [
                run_case("form-001", ["a"]),
                run_case("form-002", ["b", "x"]),
                run_case("list-001", ["d", "x"]),
            ]
        ),
        CHUNK_PARENTS,
        dataset_path="dataset.jsonl",
        run_path="run.jsonl",
        min_recall=0.8,
        min_precision=0.8,
    )

    assert report["metrics"]["child_recall"]["macro_score"] == pytest.approx(5 / 6)
    assert report["metrics"]["parent_precision"]["macro_score"] == pytest.approx(2 / 3)
    assert report["knowledge_bases"]["form"]["child_recall"]["macro_score"] == pytest.approx(0.75)
    assert report["knowledge_bases"]["list"]["parent_precision"]["macro_score"] == 0.5
    assert "overall 父块 Precision 低于 0.8" in report["violations"]
    assert "form 子块 Recall 低于 0.8" in report["violations"]


def test_build_report_rejects_missing_or_unknown_run_cases() -> None:
    cases = index_dataset([dataset_case("form-001", "form", ["a"])])

    with pytest.raises(InputError, match="缺少 case_id"):
        build_report(cases, {}, CHUNK_PARENTS, dataset_path="dataset", run_path="run")
    with pytest.raises(InputError, match="未知 case_id"):
        build_report(
            cases,
            index_run([run_case("form-001", ["a"]), run_case("js-001", ["a"])]),
            CHUNK_PARENTS,
            dataset_path="dataset",
            run_path="run",
        )


def test_index_dataset_rejects_duplicate_case_ids() -> None:
    with pytest.raises(InputError, match="重复的 case_id"):
        index_dataset(
            [
                dataset_case("form-001", "form", ["a"]),
                dataset_case("form-001", "form", ["b"]),
            ]
        )


def test_index_dataset_rejects_cross_knowledge_base_scope() -> None:
    with pytest.raises(InputError, match="只搜索一个知识库"):
        index_dataset(
            [
                {
                    "case_id": "form-001",
                    "knowledge_base": "form",
                    "search_knowledge_bases": ["form", "js"],
                    "query": "问题",
                    "reference_context_ids": ["a"],
                }
            ]
        )


def test_index_dataset_requires_target_knowledge_base_in_search_scope() -> None:
    with pytest.raises(InputError, match="必须包含目标知识库"):
        index_dataset(
            [
                {
                    "case_id": "form-001",
                    "knowledge_base": "form",
                    "search_knowledge_bases": ["js"],
                    "query": "问题",
                    "reference_context_ids": ["a"],
                }
            ]
        )


def test_index_run_requires_context_text_for_later_review() -> None:
    with pytest.raises(InputError, match="retrieved_context"):
        index_run(
            [
                {
                    "case_id": "form-001",
                    "retrieval_hits": [{"retrieval_hit_id": "a", "parent_chunk_id": None}],
                    "status": "completed",
                    "error": None,
                }
            ]
        )


def test_index_run_retains_a_parent_id_only_as_audit_metadata() -> None:
    run = index_run([run_case("form-001", ["child-1"], parent_chunk_id="parent-1")])

    assert run["form-001"]["retrieval_hits"] == [
        {
            "retrieval_hit_id": "child-1",
            "retrieved_context": "context for child-1",
            "parent_chunk_id": "parent-1",
        }
    ]


def test_index_run_normalizes_an_empty_parent_id_to_null() -> None:
    run = index_run(
        [
            {
                "case_id": "form-001",
                "retrieval_hits": [
                    {
                        "retrieval_hit_id": "child-1",
                        "retrieved_context": "context",
                        "parent_chunk_id": "",
                    }
                ],
                "status": "completed",
                "error": None,
            }
        ]
    )

    assert run["form-001"]["retrieval_hits"][0]["parent_chunk_id"] is None


def test_parent_metrics_score_contexts_without_changing_child_metrics() -> None:
    score = score_case(
        dataset_case("form-001", "form", ["child-a", "child-b"]),
        index_run(
            [
                {
                    "case_id": "form-001",
                    "retrieval_hits": [
                        {
                            "retrieval_hit_id": "other-child",
                            "retrieved_context": "parent context",
                            "parent_chunk_id": "parent-1",
                        },
                        {
                            "retrieval_hit_id": "unrelated-child",
                            "retrieved_context": "unrelated context",
                            "parent_chunk_id": "parent-2",
                        },
                    ],
                    "status": "completed",
                    "error": None,
                }
            ]
        )["form-001"],
        {"child-a": "parent-1", "child-b": "parent-1"},
    )

    assert score["recall"] == 0.0
    assert score["precision"] == 0.0
    assert score["reference_parent_context_ids"] == ["parent-1"]
    assert score["parent_recall"] == 1.0
    assert score["parent_precision"] == 0.5


def test_index_chunk_parents_uses_a_parent_or_the_child_itself() -> None:
    parents = index_chunk_parents(
        [
            {"chunk_id": "child-1", "parent_chunk_id": "parent-1"},
            {"chunk_id": "standalone", "parent_chunk_id": None},
        ]
    )

    assert parents == {"child-1": "parent-1", "standalone": "standalone"}
