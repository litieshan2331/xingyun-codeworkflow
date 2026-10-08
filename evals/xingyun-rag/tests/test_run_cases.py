"""阶段一 WeKnora 直接检索运行器测试。"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from scripts.discover_chunks import DiscoveryError, KnowledgeBaseTarget
from scripts.run_cases import (
    clip_context,
    is_original_chunk_hit,
    project_hit,
    run_cases,
    targets_by_name,
)
from scripts.rewrite_query import RewriteResult


def case(case_id: str, knowledge_base: str, query: str = "问题") -> dict[str, Any]:
    """构造一个紧凑的已标注检索案例。"""

    return {
        "case_id": case_id,
        "knowledge_base": knowledge_base,
        "query": query,
        "reference_context_ids": ["reference"],
    }


class FakeClient:
    """按案例返回预设结果的最小搜索客户端。"""

    def __init__(self, results: Mapping[str, list[Mapping[str, Any]] | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.hybrid_calls: list[tuple[str, tuple[str, ...]]] = []

    def search(self, query: str, knowledge_base_ids: tuple[str, ...]) -> list[Mapping[str, Any]]:
        self.calls.append((query, knowledge_base_ids))
        result = self.results[query]
        if isinstance(result, Exception):
            raise result
        return result

    def hybrid_search(
        self,
        query: str,
        knowledge_base_ids: tuple[str, ...],
        *,
        match_count: int,
        vector_threshold: float,
        keyword_threshold: float,
    ) -> list[Mapping[str, Any]]:
        self.hybrid_calls.append((query, knowledge_base_ids))
        result = self.results[query]
        if isinstance(result, Exception):
            raise result
        return result

    def retrieval_config(self) -> Mapping[str, Any]:
        return {"embedding_top_k": 40, "vector_threshold": 0.1, "keyword_threshold": 0.1}


class FakeRewriter:
    """返回固定改写结果的查询改写器。"""

    def __init__(self, rewritten: str) -> None:
        self.rewritten = rewritten

    def rewrite(self, query: str) -> RewriteResult:
        return RewriteResult(self.rewritten, self.rewritten != query)


def test_clip_context_reports_when_the_agent_context_is_truncated() -> None:
    assert clip_context("abcdef", 3) == ("abc", True)
    assert clip_context("abc", 3) == ("abc", False)


def test_clip_context_keeps_full_text_by_default() -> None:
    assert clip_context("abcdef", None) == ("abcdef", False)


def test_project_hit_keeps_child_id_separate_from_parent_and_context() -> None:
    result = project_hit(
        {
            "id": "child-1",
            "parent_chunk_id": "parent-1",
            "knowledge_id": "document-1",
            "chunk_index": 4,
            "chunk_type": "text",
            "score": 0.9,
            "content": "abcdef",
        },
        4,
    )

    assert result == {
        "retrieval_hit_id": "child-1",
        "retrieved_context": "abcd",
        "parent_chunk_id": "parent-1",
        "knowledge_id": "document-1",
        "chunk_index": 4,
        "chunk_type": "text",
        "score": 0.9,
        "context_truncated": True,
    }


def test_project_hit_normalizes_an_empty_parent_id_to_null() -> None:
    result = project_hit({"id": "child-1", "parent_chunk_id": "", "content": "text"}, 1200)

    assert result["parent_chunk_id"] is None


def test_is_original_chunk_hit_excludes_generated_summary() -> None:
    assert is_original_chunk_hit({"chunk_type": "text"}) is True
    assert is_original_chunk_hit({"chunk_type": "summary"}) is False


def test_run_cases_does_not_count_summary_as_a_retrieval_hit() -> None:
    client = FakeClient(
        {
            "问题": [
                {"id": "summary-1", "chunk_type": "summary", "content": "摘要"},
                {"id": "child-1", "chunk_type": "text", "content": "原文"},
            ]
        }
    )
    targets = targets_by_name((KnowledgeBaseTarget("form", ("form-kb",)),))

    results = run_cases(
        client,
        [case("form-001", "form", "问题")],
        targets,
        max_chunk_chars=1200,
    )

    assert [hit["retrieval_hit_id"] for hit in results[0]["candidate_retrieval_hits"]] == ["child-1"]
    assert [hit["retrieval_hit_id"] for hit in results[0]["final_retrieval_hits"]] == ["child-1"]


def test_run_cases_keeps_all_server_results_and_scopes_each_query_to_its_knowledge_base() -> None:
    client = FakeClient(
        {
            "表单问题": [
                {"id": "child-1", "content": "one"},
                {"id": "child-2", "content": "two"},
            ]
        }
    )
    targets = targets_by_name((KnowledgeBaseTarget("form", ("form-kb",)),))

    results = run_cases(
        client,
        [case("form-001", "form", "表单问题")],
        targets,
        max_chunk_chars=1200,
    )

    assert client.calls == [("表单问题", ("form-kb",))]
    assert client.hybrid_calls == [("表单问题", ("form-kb",))]
    assert results[0]["candidate_retrieval_hits"] == results[0]["final_retrieval_hits"]
    assert [hit["retrieval_hit_id"] for hit in results[0]["final_retrieval_hits"]] == ["child-1", "child-2"]
    assert results[0]["candidate_config"] == {
        "embedding_top_k": 40,
        "vector_threshold": 0.1,
        "keyword_threshold": 0.1,
    }
    assert results[0]["status"] == "completed"
    assert results[0]["error"] is None


def test_run_cases_searches_with_rewritten_query_and_records_both_queries() -> None:
    client = FakeClient({"完整的表单问题": [{"id": "child-1", "content": "one"}]})
    targets = targets_by_name((KnowledgeBaseTarget("form", ("form-kb",)),))

    results = run_cases(
        client,
        [case("form-001", "form", "这个问题")],
        targets,
        max_chunk_chars=1200,
        rewriter=FakeRewriter("完整的表单问题"),
    )

    assert client.calls == [("完整的表单问题", ("form-kb",))]
    assert results[0]["query"] == "这个问题"
    assert results[0]["rewritten_query"] == "完整的表单问题"
    assert results[0]["rewrite_applied"] is True
    assert results[0]["rewrite_error"] is None


def test_run_cases_rejects_cross_kb_case() -> None:
    """单工具评测拒绝跨库案例。"""

    client = FakeClient({"跨库问题": [{"id": "child-1", "content": "one"}]})
    targets = targets_by_name(
        (
            KnowledgeBaseTarget("form", ("form-kb",)),
            KnowledgeBaseTarget("js", ("js-kb",)),
        )
    )
    cross_case = case("form-001", "form", "跨库问题")
    cross_case["search_knowledge_bases"] = ["form", "js"]

    with pytest.raises(DiscoveryError, match="只使用一个知识库工具"):
        run_cases(
            client,
            [cross_case],
            targets,
            max_chunk_chars=1200,
        )


def test_run_cases_records_a_search_failure_without_discarding_other_cases() -> None:
    client = FakeClient({"失败问题": DiscoveryError("upstream unavailable")})
    targets = targets_by_name((KnowledgeBaseTarget("js", ("js-kb",)),))

    results = run_cases(
        client,
        [case("js-001", "js", "失败问题")],
        targets,
        max_chunk_chars=1200,
    )

    assert results[0]["status"] == "failed"
    assert results[0]["candidate_retrieval_hits"] == []
    assert results[0]["final_retrieval_hits"] == []
    assert results[0]["error"] == "upstream unavailable"
