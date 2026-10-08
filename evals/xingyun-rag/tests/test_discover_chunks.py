"""只读 chunk 清单采集器测试。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from scripts.discover_chunks import (
    KnowledgeBaseTarget,
    WeKnoraClient,
    _chunk_record,
    configured_targets,
    default_env_file,
    discover_chunks,
    normalize_base_url,
    parse_id_list,
)


def test_default_env_file_points_to_repository_root() -> None:
    """默认配置文件应定位到仓库根目录，而不是 evals 目录。"""

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "discover_chunks.py"
    assert default_env_file() == script_path.parents[3] / ".env"


def test_parse_id_list_deduplicates_and_discards_empty_values() -> None:
    assert parse_id_list(" kb-1, ,kb-2,kb-1 ") == ("kb-1", "kb-2")
    assert parse_id_list(None) == ()


def test_normalize_base_url_accepts_origin_or_api_root() -> None:
    assert normalize_base_url("https://weknora.example") == "https://weknora.example/api/v1"
    assert normalize_base_url("https://weknora.example/api/v1/") == "https://weknora.example/api/v1"


def test_configured_targets_uses_the_three_named_environment_variables() -> None:
    targets = configured_targets(
        {
            "XINGYUN_LIST_KB_ID": "list-1",
            "XINGYUN_FORM_KB_ID": "form-1,form-2",
            "XINGYUN_JS_KB_ID": "js-1",
        }
    )
    assert targets == (
        KnowledgeBaseTarget("list", ("list-1",)),
        KnowledgeBaseTarget("form", ("form-1", "form-2")),
        KnowledgeBaseTarget("js", ("js-1",)),
    )


def test_chunk_record_uses_raw_id_and_retains_document_metadata() -> None:
    record = _chunk_record(
        logical_name="form",
        knowledge_base_id="kb-1",
        knowledge={"id": "knowledge-1", "title": "表单设计"},
        chunk={
            "id": "chunk-1",
            "parent_chunk_id": "parent-1",
            "chunk_index": 4,
            "content": "正文",
        },
    )
    assert record["chunk_id"] == "chunk-1"
    assert record["parent_chunk_id"] == "parent-1"
    assert record["knowledge_id"] == "knowledge-1"
    assert record["chunk_index"] == 4
    assert record["content"] == "正文"
    assert len(record["content_hash"]) == 64


def test_discover_chunks_lists_documents_then_chunks_and_deduplicates_exact_repeats() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/knowledge-bases/form-kb/knowledge":
            return httpx.Response(
                200,
                json={"success": True, "data": [{"id": "knowledge-1", "title": "表单"}], "total": 1},
            )
        if path == "/api/v1/chunks/knowledge-1":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [{"id": "chunk-1", "chunk_index": 0, "content": "正文"}],
                    "total": 1,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with WeKnoraClient(
        "https://weknora.example/api/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    ) as client:
        records = discover_chunks(client, (KnowledgeBaseTarget("form", ("form-kb",)),))

    assert [record["chunk_id"] for record in records] == ["chunk-1"]
    assert requests[0].headers["X-API-Key"] == "secret"
    assert requests[0].url.params["page_size"] == "100"


def test_discover_chunks_rejects_a_chunk_id_under_two_documents() -> None:
    class FakeClient:
        def list_knowledge(self, knowledge_base_id: str):
            return iter([{"id": f"knowledge-{knowledge_base_id}"}])

        def list_chunks(self, knowledge_id: str):
            return iter([{"id": "same", "content": knowledge_id}])

    first = KnowledgeBaseTarget("form", ("kb-1", "kb-2"))
    try:
        discover_chunks(FakeClient(), (first,))
    except RuntimeError as error:
        assert "出现在多个文档下" in str(error)
    else:
        raise AssertionError("重复 chunk 标识应当触发失败")


def test_chunk_record_is_json_serializable() -> None:
    record = _chunk_record(
        logical_name="js",
        knowledge_base_id="kb-js",
        knowledge={"id": "knowledge-js"},
        chunk={"id": "chunk-js", "content": "const x = 1"},
    )
    payload = json.dumps(record, ensure_ascii=False)
    assert json.loads(payload)["chunk_id"] == "chunk-js"
