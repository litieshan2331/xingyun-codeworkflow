"""使用 RAGAS Faithfulness 评估实际回答是否由最终检索上下文支持。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping


class InputError(ValueError):
    """输入数据缺少 Faithfulness 评分所需字段。"""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise InputError(f"无法读取 {path}：{error}") from error
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise InputError(f"{path} 第 {number} 行不是有效 JSON") from error
        if not isinstance(value, dict):
            raise InputError(f"{path} 第 {number} 行必须是 JSON 对象")
        rows.append(value)
    return rows


def _read_retry_report(
    path: Path,
    dataset_path: Path,
    run_path: Path,
    dataset: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """校验旧报告的来源、模型和案例完整性，返回保留分数与待重试 ID。"""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"无法读取重试报告 {path}") from error
    if not isinstance(report, Mapping):
        raise InputError(f"重试报告 {path} 必须是 JSON 对象")
    expected_metadata = {
        "metric": "faithfulness",
        "ragas_version": "0.3.9",
        "model": os.environ.get("XINGYUN_EVAL_MODEL") or os.environ.get("VLLM_MODEL"),
        "temperature": 0,
        "enable_thinking": False,
    }
    for key, value in expected_metadata.items():
        if key not in report or report[key] != value:
            raise InputError(f"重试报告 {key} 与当前评分配置不一致，请使用原配置或重新全量评分")
    for key, input_path in (("dataset", dataset_path), ("run", run_path)):
        source = report.get(key)
        if not isinstance(source, str) or Path(source).resolve() != input_path.resolve():
            raise InputError(f"重试报告 {key} 与当前输入路径不一致")
        digest = report.get(f"{key}_sha256")
        if digest is not None and digest != hashlib.sha256(input_path.read_bytes()).hexdigest():
            raise InputError(f"重试报告 {key} 内容已改变，请重新全量评分")

    expected_cases = {case["case_id"]: case for case in dataset}
    scored: list[dict[str, Any]] = []
    retry_ids: set[str] = set()
    ids: set[str] = set()
    for key in ("cases", "unscored"):
        items = report.get(key)
        if not isinstance(items, list):
            raise InputError(f"重试报告 {path} 缺少 {key} 数组")
        for index, item in enumerate(items):
            if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
                raise InputError(f"重试报告 {key}[{index}] 缺少 case_id")
            case_id = item["case_id"]
            if case_id not in expected_cases or case_id in ids:
                raise InputError(f"重试报告案例 {case_id} 不在数据集中或重复出现")
            ids.add(case_id)
            if key == "unscored":
                retry_ids.add(case_id)
                continue
            score = item.get("faithfulness")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise InputError(f"重试报告案例 {case_id} 的 faithfulness 不是有效分数")
            if item.get("knowledge_base") != expected_cases[case_id].get("knowledge_base", "unknown"):
                raise InputError(f"重试报告案例 {case_id} 的 knowledge_base 与数据集不一致")
            scored.append(dict(item))
    if ids != set(expected_cases):
        raise InputError("重试报告未覆盖当前数据集的全部案例")
    return scored, retry_ids


def _contexts(row: Mapping[str, Any]) -> list[str]:
    hits = row.get("final_retrieval_hits")
    if not isinstance(hits, list):
        return []
    if any(
        not isinstance(hit, Mapping)
        or hit.get("context_truncated") is True
        or not isinstance(hit.get("retrieved_context"), str)
        or not hit["retrieved_context"].strip()
        for hit in hits
    ):
        return []
    return [
        hit["retrieved_context"].strip()
        for hit in hits
        if isinstance(hit, Mapping)
        and isinstance(hit.get("retrieved_context"), str)
        and hit["retrieved_context"].strip()
    ]


def _build_samples(
    dataset: list[Mapping[str, Any]], runs: Mapping[str, Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """拼接数据集和运行结果；缺少回答或上下文的案例不计为零分。"""

    samples: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for case in dataset:
        case_id = case.get("case_id")
        run = runs.get(case_id) if isinstance(case_id, str) else None
        reason = None
        if not isinstance(case_id, str) or not case_id:
            reason = "case_id 缺失"
        elif not isinstance(run, Mapping) or run.get("status") != "completed":
            reason = "运行失败或缺少运行结果"
        #elif case.get("unambiguous") is not True:
        #    reason = "案例未标记为 unambiguous"
        elif not isinstance(run.get("response"), str) or not run["response"].strip():
            reason = "运行结果缺少 response"
        elif not _contexts(run):
            reason = "最终检索文本缺失、不完整或被截断"
        elif not isinstance(case.get("query"), str) or not case["query"].strip():
            raise InputError(f"{case_id} 的 query 必须是非空字符串")
        if reason:
            skipped.append({"case_id": case_id, "reason": reason})
            continue
        samples.append(
            {
                "case_id": case_id,
                "knowledge_base": case.get("knowledge_base", "unknown"),
                "user_input": str(case["query"]),
                "response": str(run["response"]).strip(),
                "retrieved_contexts": _contexts(run),
            }
        )
    return samples, skipped


def _judge_config() -> dict[str, Any]:
    """读取本机 vLLM 判分配置；模型名和服务配置必须显式提供。"""
    model = os.environ.get("XINGYUN_EVAL_MODEL") or os.environ.get("VLLM_MODEL")
    base_url = os.environ.get("VLLM_BASE_URL")
    api_key = os.environ.get("VLLM_API_KEY")
    if not model or not model.strip():
        raise InputError("请在根目录 .env 设置 XINGYUN_EVAL_MODEL 或 VLLM_MODEL")
    if not base_url or not api_key:
        raise InputError("请在根目录 .env 设置 VLLM_BASE_URL 和 VLLM_API_KEY")
    return {"model": model.strip(), "base_url": base_url, "api_key": api_key, "temperature": 0}


def _score(samples: list[dict[str, Any]]) -> list[float]:
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness
    from ragas.run_config import RunConfig

    config = _judge_config()
    judge = LangchainLLMWrapper(
        ChatOpenAI(
            **config,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        ),
        # RAGAS 默认在异步调用时重设 temperature；保留模型配置的 0。
        bypass_temperature=True,
    )
    inputs = [
        {key: sample[key] for key in ("user_input", "response", "retrieved_contexts")}
        for sample in samples
    ]
    result = evaluate(
        EvaluationDataset.from_list(inputs),
        metrics=[Faithfulness()],
        llm=judge,
        run_config=RunConfig(max_workers=8),
    )
    return [float(row["faithfulness"]) for row in result.scores]


def main() -> int:
    """写入逐案例和分组报告；存在不可评分案例时返回 1。"""
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
    parser = argparse.ArgumentParser(description="评估星云 Agent 的 RAGAS Faithfulness")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--retry-report",
        type=Path,
        help="只重试该报告 unscored 中的案例，并复用已有 cases 分数。",
    )
    args = parser.parse_args()

    if args.out.resolve() in {args.dataset.resolve(), args.run.resolve()}:
        raise InputError("--out 不能覆盖数据集或运行文件")

    dataset = _read_jsonl(args.dataset)
    run_rows = _read_jsonl(args.run)
    runs: dict[str, Mapping[str, Any]] = {}
    for rows in (dataset, run_rows):
        ids: set[str] = set()
        for row in rows:
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
                raise InputError("case_id 必须是唯一非空字符串")
            ids.add(case_id)
    runs = {row["case_id"]: row for row in run_rows}
    all_samples, all_skipped = _build_samples(dataset, runs)
    if not args.retry_report:
        samples = all_samples
        skipped = all_skipped
        previous_scored: list[dict[str, Any]] = []
    else:
        previous_scored, retry_ids = _read_retry_report(
            args.retry_report, args.dataset, args.run, dataset
        )
        samples = [sample for sample in all_samples if sample["case_id"] in retry_ids]
        skipped = [item for item in all_skipped if item["case_id"] in retry_ids]
    scores = _score(samples) if samples else []
    scored = [dict(item) for item in previous_scored]
    for sample, score in zip(samples, scores, strict=True):
        if not math.isfinite(score) or not 0 <= score <= 1:
            skipped.append({"case_id": sample["case_id"], "reason": "RAGAS 未返回有效分数"})
            continue
        scored.append({"case_id": sample["case_id"], "knowledge_base": sample["knowledge_base"], "faithfulness": score})
    order = {case["case_id"]: index for index, case in enumerate(dataset)}
    scored.sort(key=lambda item: order[item["case_id"]])
    skipped.sort(key=lambda item: order[item["case_id"]])
    groups: dict[str, list[float]] = defaultdict(list)
    for row in scored:
        groups[row["knowledge_base"]].append(row["faithfulness"])
    report = {
        "metric": "faithfulness",
        "ragas_version": "0.3.9",
        "dataset": str(args.dataset),
        "run": str(args.run),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "run_sha256": hashlib.sha256(args.run.read_bytes()).hexdigest(),
        "retry_report": str(args.retry_report) if args.retry_report else None,
        "retried_count": len(samples) if args.retry_report else 0,
        "model": os.environ.get("XINGYUN_EVAL_MODEL") or os.environ.get("VLLM_MODEL"),
        "temperature": 0,
        "enable_thinking": False,
        "scored_count": len(scored),
        "unscored_count": len(skipped),
        "macro_score": sum(row["faithfulness"] for row in scored) / len(scored) if scored else None,
        "by_knowledge_base": {
            name: {"count": len(values), "score": sum(values) / len(values)}
            for name, values in sorted(groups.items())
        },
        "cases": scored,
        "unscored": skipped,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"macro_score": report["macro_score"], "scored_count": len(scored), "retried_count": report["retried_count"]}, ensure_ascii=False))
    return 1 if skipped or not scored else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InputError as error:
        print(f"score_faithfulness：{error}", file=sys.stderr)
        raise SystemExit(2) from error
