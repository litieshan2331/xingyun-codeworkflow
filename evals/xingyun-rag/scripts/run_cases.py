"""通过 WeKnora 运行阶段一检索案例，并保存结构化命中结果。

此运行器在页面或 JavaScript 生成前测量检索器。每个案例只调用一个知识库工具，并在检索前执行与 WeKnora 查询理解阶段一致的单轮问题改写，记录服务端返回的全部搜索命中。默认保存完整上下文；需要控制文件大小时可显式设置字符上限。

每个案例同时保存 RRF 后、Rerank 前的候选结果和 Rerank 后的最终结果。候选结果用于 Recall，最终结果用于父块 Precision。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from dotenv import load_dotenv

try:
    from scripts.discover_chunks import (
        DEFAULT_TIMEOUT_SECONDS,
        DiscoveryError,
        KnowledgeBaseTarget,
        WeKnoraClient,
        configured_targets,
        default_env_file,
    )
    from scripts.score_retrieval import index_dataset, read_jsonl
    from scripts.rewrite_query import QueryRewriter, RewriteResult
except ImportError:
    from discover_chunks import (
        DEFAULT_TIMEOUT_SECONDS,
        DiscoveryError,
        KnowledgeBaseTarget,
        WeKnoraClient,
        configured_targets,
        default_env_file,
    )
    from score_retrieval import index_dataset, read_jsonl
    from rewrite_query import QueryRewriter, RewriteResult


DEFAULT_EMBEDDING_TOP_K = 40
DEFAULT_VECTOR_THRESHOLD = 0.1
DEFAULT_KEYWORD_THRESHOLD = 0.1


def _string(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError(f"{description} 必须是非空字符串")
    return value.strip()


def _optional_string(value: Any, description: str) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _string(value, description)


def clip_context(content: str, max_chars: int | None) -> tuple[str, bool]:
    """按可选字符上限截取搜索段落；上限为空时保留完整文本。"""

    if max_chars is None:
        return content, False
    return content[:max_chars], len(content) > max_chars


def project_hit(hit: Mapping[str, Any], max_chunk_chars: int | None) -> dict[str, Any]:
    """将一个原始搜索命中投影为阶段一运行结果。

    子 chunk ID 是唯一评分键；WeKnora 将子命中扩展为父上下文时，父 ID 用于描述上下文来源。
    """

    content = hit.get("content")
    if not isinstance(content, str) or not content:
        raise DiscoveryError("搜索结果 content 必须是非空字符串")
    retrieved_context, truncated = clip_context(content, max_chunk_chars)
    return {
        "retrieval_hit_id": _string(hit.get("id"), "search result id"),
        "retrieved_context": retrieved_context,
        "parent_chunk_id": _optional_string(
            hit.get("parent_chunk_id"),
            "search result parent_chunk_id",
        ),
        "knowledge_id": _optional_string(hit.get("knowledge_id"), "search result knowledge_id"),
        "chunk_index": hit.get("chunk_index"),
        "chunk_type": hit.get("chunk_type"),
        "score": hit.get("score"),
        "context_truncated": truncated,
    }


def is_original_chunk_hit(hit: Mapping[str, Any]) -> bool:
    """只保留原始文本 chunk；WeKnora 生成的 summary 不参与本阶段评分。"""

    return hit.get("chunk_type") != "summary"


def targets_by_name(
    targets: Iterable[KnowledgeBaseTarget],
) -> dict[str, KnowledgeBaseTarget]:
    """按逻辑数据集名称索引配置的知识库目标。"""

    return {target.name: target for target in targets}


def run_cases(
    client: WeKnoraClient,
    cases: Iterable[Mapping[str, Any]],
    targets: Mapping[str, KnowledgeBaseTarget],
    *,
    max_chunk_chars: int | None,
    rewriter: QueryRewriter | None = None,
    embedding_top_k: int = DEFAULT_EMBEDDING_TOP_K,
    vector_threshold: float = DEFAULT_VECTOR_THRESHOLD,
    keyword_threshold: float = DEFAULT_KEYWORD_THRESHOLD,
) -> list[dict[str, Any]]:
    """搜索每个已标注案例，并逐例保留成功或失败结果。"""

    output: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["case_id"])
        knowledge_base = str(case["knowledge_base"])
        search_knowledge_bases = tuple(
            str(name)
            for name in case.get("search_knowledge_bases", [knowledge_base])
        )
        target_knowledge_bases = tuple(
            str(name)
            for name in case.get("target_knowledge_bases", [knowledge_base])
        )
        if not search_knowledge_bases:
            raise DiscoveryError(f"案例 {case_id!r} 没有配置搜索知识库")
        if len(search_knowledge_bases) != 1 or len(target_knowledge_bases) != 1:
            raise DiscoveryError(
                f"案例 {case_id!r} 必须只使用一个知识库工具；"
                "跨库案例不属于当前单工具评测"
            )
        search_ids: list[str] = []
        for search_name in search_knowledge_bases:
            target = targets.get(search_name)
            if target is None:
                raise DiscoveryError(
                    f"案例 {case_id!r} 使用了未配置的知识库 {search_name!r}"
                )
            search_ids.extend(target.ids)
        search_ids = list(dict.fromkeys(search_ids))
        if not search_ids:
            raise DiscoveryError(f"案例 {case_id!r} 的搜索知识库没有可用 ID")
        original_query = _string(case["query"], f"案例 {case_id!r} 的 query")
        rewrite = (
            rewriter.rewrite(original_query)
            if rewriter is not None
            else RewriteResult(original_query, False, "未启用查询改写")
        )
        search_query = rewrite.query
        common_fields = {
            "query": original_query,
            "rewritten_query": search_query,
            "rewrite_applied": rewrite.applied,
            "rewrite_error": rewrite.error,
        }
        try:
            candidate_hits = [
                hit
                for hit in client.hybrid_search(
                    search_query,
                    tuple(search_ids),
                    match_count=embedding_top_k,
                    vector_threshold=vector_threshold,
                    keyword_threshold=keyword_threshold,
                )
                if is_original_chunk_hit(hit)
            ]
            raw_hits = [
                hit
                for hit in client.search(search_query, tuple(search_ids))
                if is_original_chunk_hit(hit)
            ]
            candidate_retrieval_hits = [
                project_hit(hit, max_chunk_chars) for hit in candidate_hits
            ]
            final_retrieval_hits = [project_hit(hit, max_chunk_chars) for hit in raw_hits]
        except DiscoveryError as error:
            output.append(
                {
                    "case_id": case_id,
                    "knowledge_base": knowledge_base,
                    "search_knowledge_bases": list(search_knowledge_bases),
                    "target_knowledge_bases": list(target_knowledge_bases),
                    **{
                        field: case[field]
                        for field in ("route_group", "query_type")
                        if field in case
                    },
                    "knowledge_base_ids": search_ids,
                    **common_fields,
                    "candidate_retrieval_hits": [],
                    "final_retrieval_hits": [],
                    "candidate_error": str(error),
                    "status": "failed",
                    "error": str(error),
                }
            )
            continue
        output.append(
            {
                "case_id": case_id,
                "knowledge_base": knowledge_base,
                "search_knowledge_bases": list(search_knowledge_bases),
                "target_knowledge_bases": list(target_knowledge_bases),
                **{
                    field: case[field]
                    for field in ("route_group", "query_type")
                    if field in case
                },
                "knowledge_base_ids": search_ids,
                **common_fields,
                "candidate_retrieval_hits": candidate_retrieval_hits,
                "final_retrieval_hits": final_retrieval_hits,
                "candidate_config": {
                    "embedding_top_k": embedding_top_k,
                    "vector_threshold": vector_threshold,
                    "keyword_threshold": keyword_threshold,
                },
                "candidate_error": None,
                "status": "completed",
                "error": None,
            }
        )
    return output


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """写入 JSONL 结果，不创建包含密钥或请求头的记录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("值必须是正整数") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("值必须是正整数")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """构建阶段一检索运行器的命令行解析器。"""

    parser = argparse.ArgumentParser(
        description="通过 WeKnora 运行已标注的星云检索问题。"
    )
    parser.add_argument("--dataset", type=Path, required=True, help="已标注的检索 JSONL。")
    parser.add_argument("--out", type=Path, required=True, help="运行结果 JSONL 路径。")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=default_env_file(),
        help="包含 WeKnora 配置的环境文件（默认：仓库根目录 .env）。",
    )
    parser.add_argument(
        "--rewrite-model",
        default=None,
        help="查询改写模型名称（默认读取 XINGYUN_REWRITE_MODEL 或 Qwen/Qwen3.6-27B-FP8）。",
    )
    parser.add_argument(
        "--rewrite-base-url",
        default=None,
        help="OpenAI 兼容改写服务地址（默认读取 VLLM_BASE_URL）。",
    )
    parser.add_argument(
        "--rewrite-api-key",
        default=None,
        help="改写服务密钥（默认读取 VLLM_API_KEY）。",
    )
    parser.add_argument(
        "--no-rewrite",
        action="store_true",
        help="关闭查询改写，仅用于对照实验。",
    )
    parser.add_argument(
        "--max-chunk-chars",
        type=_positive_int,
        default=None,
        help=(
            "每个命中保留的最大上下文字符数 "
            "（默认保留完整上下文，用于 Faithfulness 生成）。"
        ),
    )
    parser.add_argument(
        "--embedding-top-k",
        type=_positive_int,
        default=None,
        help="初步候选召回 TopK；默认读取 WeKnora 租户配置。",
    )
    parser.add_argument(
        "--vector-threshold",
        type=float,
        default=None,
        help="初步候选的向量相似度阈值；默认读取 WeKnora 租户配置。",
    )
    parser.add_argument(
        "--keyword-threshold",
        type=float,
        default=None,
        help="初步候选的关键词匹配阈值；默认读取 WeKnora 租户配置。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP 超时时间（秒，默认：{DEFAULT_TIMEOUT_SECONDS}）。",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """加载配置并运行全部案例；任一案例失败时返回非零状态。"""

    load_dotenv(args.env_file, override=False)
    base_url = os.environ.get("WEKNORA_BASE_URL")
    api_key = os.environ.get("WEKNORA_API_KEY")
    if not base_url:
        raise DiscoveryError("缺少 WEKNORA_BASE_URL")
    if not api_key:
        raise DiscoveryError("缺少 WEKNORA_API_KEY")

    rewriter: QueryRewriter | None = None
    if not args.no_rewrite:
        rewrite_base_url = args.rewrite_base_url or os.environ.get("VLLM_BASE_URL")
        rewrite_api_key = args.rewrite_api_key or os.environ.get("VLLM_API_KEY")
        rewrite_model = (
            args.rewrite_model
            or os.environ.get("XINGYUN_REWRITE_MODEL")
            or "Qwen/Qwen3.6-27B-FP8"
        )
        if not rewrite_base_url or not rewrite_api_key:
            raise DiscoveryError(
                "查询改写需要 VLLM_BASE_URL 和 VLLM_API_KEY；"
                "如需对照实验请显式使用 --no-rewrite"
            )
        rewriter = QueryRewriter(
            base_url=rewrite_base_url,
            api_key=rewrite_api_key,
            model=rewrite_model,
            timeout_seconds=args.timeout,
        )

    cases = list(index_dataset(read_jsonl(args.dataset)).values())
    targets = targets_by_name(configured_targets(os.environ))
    with WeKnoraClient(
        base_url=base_url,
        api_key=api_key,
        tenant_id=os.environ.get("WEKNORA_TENANT_ID"),
        timeout_seconds=args.timeout,
    ) as client:
        config = client.retrieval_config()
        embedding_top_k = int(
            args.embedding_top_k
            if args.embedding_top_k is not None
            else config.get("embedding_top_k", DEFAULT_EMBEDDING_TOP_K)
        )
        vector_threshold = float(
            args.vector_threshold
            if args.vector_threshold is not None
            else config.get("vector_threshold", DEFAULT_VECTOR_THRESHOLD)
        )
        keyword_threshold = float(
            args.keyword_threshold
            if args.keyword_threshold is not None
            else config.get("keyword_threshold", DEFAULT_KEYWORD_THRESHOLD)
        )
        if embedding_top_k <= 0 or not 0 <= vector_threshold <= 1 or not 0 <= keyword_threshold <= 1:
            raise DiscoveryError("WeKnora 检索配置中的 embedding_top_k/阈值无效")
        rows = run_cases(
            client,
            cases,
            targets,
            max_chunk_chars=args.max_chunk_chars,
            rewriter=rewriter,
            embedding_top_k=embedding_top_k,
            vector_threshold=vector_threshold,
            keyword_threshold=keyword_threshold,
        )
    write_jsonl(args.out, rows)
    failed = sum(row["status"] != "completed" for row in rows)
    print(f"已将 {len(rows)} 个案例写入 {args.out}（失败 {failed} 个）")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """运行检索采集器；配置或输入无效时返回 2。"""

    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (DiscoveryError, ValueError) as error:
        print(f"run_cases：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
