"""发现阶段一检索数据集使用的 chunk 清单。

脚本默认读取仓库根目录的 ``.env``，列出三个星云知识库中的知识文档，并获取每个文档的全部 chunk。持久化的 ``chunk_id`` 是
WeKnora 原始子 chunk 的 ``id``；文档 ID、序号和可选父块 ID 仅作为标注元数据保留。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import quote

import httpx
from dotenv import load_dotenv


KNOWLEDGE_BASE_ENV = {
    "list": "XINGYUN_LIST_KB_ID",
    "form": "XINGYUN_FORM_KB_ID",
    "js": "XINGYUN_JS_KB_ID",
}
DEFAULT_PAGE_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 200.0
DEFAULT_OUTPUT = Path("datasets/chunks.v1.jsonl")
DEFAULT_MANIFEST_OUTPUT = Path("datasets/kb-manifest.v1.json")


class DiscoveryError(RuntimeError):
    """当 WeKnora 响应无法生成有效 chunk 记录时抛出。"""


@dataclass(frozen=True)
class KnowledgeBaseTarget:
    """一个逻辑测评知识库及其配置的 WeKnora ID。"""

    name: str
    ids: tuple[str, ...]


def parse_id_list(raw: str | None) -> tuple[str, ...]:
    """将逗号分隔的环境变量值解析为非空且去重的 ID。"""

    if raw is None:
        return ()
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return tuple(dict.fromkeys(values))


def normalize_base_url(raw: str) -> str:
    """将 WeKnora 源站或 API 根地址规范化为以 ``/api/v1`` 结尾的 URL。"""

    value = raw.strip().rstrip("/")
    if not value:
        raise DiscoveryError("WEKNORA_BASE_URL 为空")
    if value.endswith("/api/v1"):
        return value
    return f"{value}/api/v1"


def default_env_file() -> Path:
    """返回相对于本测评目录的仓库根目录 `.env` 路径。"""

    # 当前文件位于仓库根目录的 evals/xingyun-rag/scripts 下，向上三级才是仓库根目录。
    return Path(__file__).resolve().parents[3] / ".env"


def configured_targets(environ: Mapping[str, str]) -> tuple[KnowledgeBaseTarget, ...]:
    """从环境变量解析三个逻辑知识库目标。"""

    targets: list[KnowledgeBaseTarget] = []
    for name, variable in KNOWLEDGE_BASE_ENV.items():
        ids = parse_id_list(environ.get(variable))
        if not ids:
            raise DiscoveryError(f"缺少 {variable} 或其中没有知识库 ID")
        targets.append(KnowledgeBaseTarget(name=name, ids=ids))
    return tuple(targets)


def _as_object(value: Any, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DiscoveryError(f"{description} 必须是 JSON 对象")
    return value


def _as_list(value: Any, description: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise DiscoveryError(f"{description} 必须是 JSON 数组")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        result.append(_as_object(item, f"{description}[{index}]"))
    return result


class WeKnoraClient:
    """用于 WeKnora 知识和 chunk 接口的只读客户端。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        tenant_id: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = normalize_base_url(base_url)
        self._headers = {
            "Accept": "application/json",
            "X-API-Key": api_key,
        }
        if tenant_id:
            self._headers["X-Tenant-ID"] = tenant_id
        self._client = httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> "WeKnoraClient":
        self._client.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self._client.__exit__(exc_type, exc_value, traceback)

    def _get(self, path: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise DiscoveryError(f"GET {path} 失败：{error}") from error
        try:
            payload = _as_object(response.json(), f"GET {path} 响应")
        except (ValueError, DiscoveryError) as error:
            raise DiscoveryError(f"GET {path} 返回的不是有效 JSON") from error
        if payload.get("success") is False:
            message = payload.get("message") or payload.get("error") or "未知 API 错误"
            raise DiscoveryError(f"GET {path} 返回 success=false：{message}")
        return payload

    def _post(self, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = self._client.post(path, json=body)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise DiscoveryError(f"POST {path} 失败：{error}") from error
        try:
            payload = _as_object(response.json(), f"POST {path} 响应")
        except (ValueError, DiscoveryError) as error:
            raise DiscoveryError(f"POST {path} 返回的不是有效 JSON") from error
        if payload.get("success") is False:
            message = payload.get("message") or payload.get("error") or "未知 API 错误"
            raise DiscoveryError(f"POST {path} 返回 success=false：{message}")
        return payload

    def _paged(self, path: str, *, extra_params: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
        page = 1
        page_size = DEFAULT_PAGE_SIZE
        while True:
            payload = self._get(
                path,
                {**extra_params, "page": page, "page_size": page_size},
            )
            items = _as_list(payload.get("data"), f"GET {path} data")
            yield from items

            if not items:
                return
            returned_page = payload.get("page")
            returned_size = payload.get("page_size")
            if isinstance(returned_page, int) and returned_page >= page:
                page = returned_page
            if isinstance(returned_size, int) and returned_size > 0:
                page_size = returned_size
            total = payload.get("total")
            if isinstance(total, int) and page * page_size >= total:
                return
            if len(items) < page_size:
                return
            page += 1

    def list_knowledge(self, knowledge_base_id: str) -> Iterator[Mapping[str, Any]]:
        """返回一个知识库 ID 下的全部知识文档。"""

        path = f"/knowledge-bases/{quote(knowledge_base_id, safe='')}/knowledge"
        return self._paged(path, extra_params={})

    def list_chunks(self, knowledge_id: str) -> Iterator[Mapping[str, Any]]:
        """返回一个知识文档 ID 下的全部 chunk。"""

        path = f"/chunks/{quote(knowledge_id, safe='')}"
        return self._paged(path, extra_params={})

    def search(
        self,
        query: str,
        knowledge_base_ids: tuple[str, ...],
    ) -> list[Mapping[str, Any]]:
        """返回指定知识库的原始 WeKnora 搜索结果。"""

        payload = self._post(
            "/knowledge-search",
            {"query": query, "knowledge_base_ids": list(knowledge_base_ids)},
        )
        return _as_list(payload.get("data"), "POST /knowledge-search data")

    def hybrid_search(
        self,
        query: str,
        knowledge_base_ids: tuple[str, ...],
        *,
        match_count: int,
        vector_threshold: float,
        keyword_threshold: float,
    ) -> list[Mapping[str, Any]]:
        """返回 RRF 融合且尚未经过 Rerank 的候选 chunk。"""

        if not knowledge_base_ids:
            raise DiscoveryError("hybrid-search 至少需要一个知识库 ID")
        primary_id = quote(knowledge_base_ids[0], safe="")
        payload = self._post(
            f"/knowledge-bases/{primary_id}/hybrid-search",
            {
                "query_text": query,
                "knowledge_base_ids": list(knowledge_base_ids),
                "match_count": match_count,
                "vector_threshold": vector_threshold,
                "keyword_threshold": keyword_threshold,
                "skip_context_enrichment": True,
            },
        )
        return _as_list(payload.get("data"), "POST /knowledge-bases/:id/hybrid-search data")

    def retrieval_config(self) -> Mapping[str, Any]:
        """读取当前租户的向量、关键词和候选 TopK 配置。"""

        payload = self._get("/tenants/kv/retrieval-config", {})
        return _as_object(payload.get("data"), "GET /tenants/kv/retrieval-config data")

    def close(self) -> None:
        """关闭底层 HTTP 客户端。"""

        self._client.close()


def _string_field(item: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _chunk_record(
    *,
    logical_name: str,
    knowledge_base_id: str,
    knowledge: Mapping[str, Any],
    chunk: Mapping[str, Any],
) -> dict[str, Any]:
    """将一个 API chunk 投影为稳定的标注清单记录。"""

    knowledge_id = _string_field(knowledge, "id", "knowledge_id")
    if knowledge_id is None:
            raise DiscoveryError(f"知识库 {knowledge_base_id!r} 的知识文档没有 ID")
    chunk_id = _string_field(chunk, "id")
    if chunk_id is None:
        raise DiscoveryError(f"知识文档 {knowledge_id!r} 下的 chunk 没有原始 ID")
    content = chunk.get("content")
    if not isinstance(content, str):
        raise DiscoveryError(f"chunk {chunk_id!r} 没有字符串内容")

    record: dict[str, Any] = {
        "knowledge_base": logical_name,
        "knowledge_base_id": knowledge_base_id,
        "knowledge_id": knowledge_id,
        "chunk_id": chunk_id,
        "parent_chunk_id": _string_field(chunk, "parent_chunk_id"),
        "chunk_index": chunk.get("chunk_index", chunk.get("index")),
        "chunk_type": chunk.get("chunk_type", chunk.get("type")),
        "document_title": _string_field(knowledge, "title", "name", "file_name") or "",
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    return record


def discover_chunks(
    client: WeKnoraClient,
    targets: tuple[KnowledgeBaseTarget, ...],
) -> list[dict[str, Any]]:
    """获取并校验配置的逻辑知识库中的全部 chunk。"""

    records: list[dict[str, Any]] = []
    seen: dict[str, tuple[str, str]] = {}
    for target in targets:
        for knowledge_base_id in target.ids:
            for knowledge in client.list_knowledge(knowledge_base_id):
                knowledge_id = _string_field(knowledge, "id", "knowledge_id")
                if knowledge_id is None:
                    raise DiscoveryError(f"知识库 {knowledge_base_id!r} 的知识文档没有 ID")
                for chunk in client.list_chunks(knowledge_id):
                    record = _chunk_record(
                        logical_name=target.name,
                        knowledge_base_id=knowledge_base_id,
                        knowledge=knowledge,
                        chunk=chunk,
                    )
                    identity = (record["knowledge_base_id"], record["knowledge_id"])
                    previous = seen.get(record["chunk_id"])
                    if previous is not None and previous != identity:
                        raise DiscoveryError(
                            f"chunk ID {record['chunk_id']!r} 出现在多个文档下：{previous!r} 和 {identity!r}"
                        )
                    if previous is None:
                        seen[record["chunk_id"]] = identity
                        records.append(record)

    records.sort(
        key=lambda item: (
            item["knowledge_base"],
            item["knowledge_base_id"],
            item["knowledge_id"],
            item["chunk_index"] if isinstance(item["chunk_index"], int) else -1,
            item["chunk_id"],
        )
    )
    return records


def _write_jsonl(path: Path, records: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_manifest(
    path: Path,
    targets: tuple[KnowledgeBaseTarget, ...],
    records: list[Mapping[str, Any]],
) -> None:
    counts: dict[str, dict[str, int]] = {
        target.name: {knowledge_base_id: 0 for knowledge_base_id in target.ids}
        for target in targets
    }
    documents: dict[tuple[str, str], set[str]] = {}
    for record in records:
        logical_name = str(record["knowledge_base"])
        knowledge_base_id = str(record["knowledge_base_id"])
        counts[logical_name][knowledge_base_id] += 1
        documents.setdefault((logical_name, knowledge_base_id), set()).add(str(record["knowledge_id"]))

    manifest = {
        "format": "xingyun-rag-chunk-manifest/v1",
        "chunk_id_field": "id",
        "chunk_id_source": "WeKnora knowledge-search data[].id or chunks data[].id",
        "parent_chunk_id_field": "parent_chunk_id",
        "knowledge_bases": [
            {
                "name": target.name,
                "ids": list(target.ids),
                "document_count": sum(
                    len(documents.get((target.name, knowledge_base_id), set()))
                    for knowledge_base_id in target.ids
                ),
                "chunk_counts": {
                    knowledge_base_id: counts[target.name][knowledge_base_id]
                    for knowledge_base_id in target.ids
                },
            }
            for target in targets
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""

    parser = argparse.ArgumentParser(
        description="获取 WeKnora 原始 chunk ID 和文本，供检索标注使用。"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=default_env_file(),
        help="包含 WeKnora 配置的环境文件（默认：仓库根目录 .env）。",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"chunk 清单 JSONL 路径（默认：{DEFAULT_OUTPUT}）。",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=DEFAULT_MANIFEST_OUTPUT,
        help=f"manifest JSON 路径（默认：{DEFAULT_MANIFEST_OUTPUT}）。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP 超时时间（秒，默认：{DEFAULT_TIMEOUT_SECONDS}）。",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """运行发现流程并写入清单与 manifest。"""

    load_dotenv(args.env_file, override=False)
    base_url = os.environ.get("WEKNORA_BASE_URL")
    api_key = os.environ.get("WEKNORA_API_KEY")
    if not base_url:
        raise DiscoveryError("缺少 WEKNORA_BASE_URL")
    if not api_key:
        raise DiscoveryError("缺少 WEKNORA_API_KEY")
    targets = configured_targets(os.environ)

    with WeKnoraClient(
        base_url=base_url,
        api_key=api_key,
        tenant_id=os.environ.get("WEKNORA_TENANT_ID"),
        timeout_seconds=args.timeout,
    ) as client:
        records = discover_chunks(client, targets)

    _write_jsonl(args.out, records)
    _write_manifest(args.manifest_out, targets, records)
    print(f"已将 {len(records)} 个 chunk 写入 {args.out}")
    print(f"已将 manifest 写入 {args.manifest_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """运行 chunk 发现命令，并报告配置或 API 失败。"""

    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except DiscoveryError as error:
        print(f"discover_chunks：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
