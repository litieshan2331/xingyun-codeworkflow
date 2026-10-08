"""复用检索运行结果，单独生成 Faithfulness 所需的 Agent 回答。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Protocol

from dotenv import load_dotenv

try:
    from scripts.score_retrieval import read_jsonl
except ImportError:
    from score_retrieval import read_jsonl


class InputError(ValueError):
    """输入运行结果或生成配置无效。"""


class CompletionClient(Protocol):
    """OpenAI chat completions 调用接口。"""

    def create(self, **kwargs: Any) -> Any: ...


def _config() -> tuple[str, str, str]:
    model = os.environ.get("XINGYUN_GENERATION_MODEL") or os.environ.get("VLLM_MODEL")
    base_url = os.environ.get("VLLM_BASE_URL")
    api_key = os.environ.get("VLLM_API_KEY")
    if not model:
        raise InputError("请在根目录 .env 设置 XINGYUN_GENERATION_MODEL 或 VLLM_MODEL")
    if not base_url or not api_key:
        raise InputError("请在根目录 .env 设置 VLLM_BASE_URL 和 VLLM_API_KEY")
    return model, base_url, api_key


def _context(row: Mapping[str, Any]) -> str:
    hits = row.get("final_retrieval_hits")
    if not isinstance(hits, list):
        return ""
    if any(
        not isinstance(hit, Mapping)
        or hit.get("context_truncated") is True
        or not isinstance(hit.get("retrieved_context"), str)
        or not hit["retrieved_context"].strip()
        for hit in hits
    ):
        return ""
    parts = [
        hit["retrieved_context"].strip()
        for hit in hits
        if isinstance(hit, Mapping)
        and isinstance(hit.get("retrieved_context"), str)
        and hit["retrieved_context"].strip()
    ]
    return "\n\n---\n\n".join(parts)


def _answer(client: CompletionClient, row: Mapping[str, Any], model: str) -> str:
    query = row.get("query")
    context = _context(row)
    if not isinstance(query, str) or not query.strip():
        raise InputError(f"案例 {row.get('case_id', '<unknown>')} 缺少 query")
    if not context:
        raise InputError(f"案例 {row.get('case_id', '<unknown>')} 缺少 final_retrieval_hits 文本")
    response = client.create(
        model=model,
        temperature=0,
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": "你是星云知识库问答助手。只根据给定检索上下文回答问题；上下文没有依据的内容明确说无法确认。不要编造规则。",
            },
            {
                "role": "user",
                "content": f"问题：{query.strip()}\n\n检索上下文：\n{context}",
            },
        ],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    choices = getattr(response, "choices", None)
    if not choices:
        raise InputError(f"案例 {row.get('case_id', '<unknown>')} 的模型响应没有 choices")
    if getattr(choices[0], "finish_reason", "stop") != "stop":
        raise InputError(f"案例 {row.get('case_id', '<unknown>')} 的回答未正常完成")
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if not isinstance(content, str) or not content.strip():
        raise InputError(f"案例 {row.get('case_id', '<unknown>')} 的模型响应没有文本")
    return content.strip()


def run(rows: list[Mapping[str, Any]], client: CompletionClient, model: str) -> list[dict[str, Any]]:
    """为每个成功检索案例补充 response，保留原始检索字段。"""
    output: list[dict[str, Any]] = []
    for row in rows:
        result = dict(row)
        if row.get("status") != "completed":
            result["response"] = None
            result["generation_status"] = "skipped"
            result["generation_error"] = "检索运行未完成"
        else:
            result["generation_config"] = {"model": model, "temperature": 0, "max_tokens": 4096, "enable_thinking": False, "prompt_version": "knowledge-qa.v1"}
            try:
                result["response"] = _answer(client, row, model)
                result["generation_status"] = "completed"
                result["generation_error"] = None
            except Exception as error:
                result["response"] = None
                result["generation_status"] = "failed"
                result["generation_error"] = str(error) if isinstance(error, InputError) else f"模型调用失败：{type(error).__name__}"
        output.append(result)
    return output


def main() -> int:
    """读取检索运行结果并写入带回答的 Faithfulness 运行结果。"""
    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
    parser = argparse.ArgumentParser(description="为已有检索结果生成 Faithfulness 回答")
    parser.add_argument("--run", type=Path, required=True, help="已有 run_cases.py 输出")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        from openai import OpenAI

        if args.run.resolve() == args.out.resolve():
            raise InputError("--out 必须与 --run 使用不同路径，保留原始检索结果")
        model, base_url, api_key = _config()
        client = OpenAI(base_url=base_url, api_key=api_key)
        rows = read_jsonl(args.run)
        output = run(rows, client.chat.completions, model)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in output) + "\n",
            encoding="utf-8",
        )
        failed = sum(row.get("generation_status") != "completed" for row in output)
        print(f"已生成 {len(output) - failed}/{len(output)} 条回答，写入 {args.out}")
        return 1 if failed else 0
    except (InputError, OSError, ValueError) as error:
        print(f"run_faithfulness_cases：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
