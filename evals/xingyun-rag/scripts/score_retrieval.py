"""根据已标注 JSONL 评估阶段一的子命中和父上下文检索。

子 chunk Recall 和 Precision 比较 WeKnora 原始子 chunk ID。父块 Recall 和 Precision 比较模型实际获得的上下文块：每个参考子
chunk 通过清单映射到父块；没有父块时映射到自身。当前数据集每题只搜索一个知识库工具。失败或不完整的运行会标记为不可评分，而不是转换为零分。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


class InputError(ValueError):
    """当已标注数据集或检索运行结果违反 JSONL 格式时抛出。"""


def _object(value: Any, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputError(f"{description} 必须是 JSON 对象")
    return value


def _string(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{description} 必须是非空字符串")
    return value.strip()


def _string_list(value: Any, description: str) -> list[str]:
    if not isinstance(value, list):
        raise InputError(f"{description} 必须是 JSON 数组")
    values = [_string(item, f"{description}[{index}]") for index, item in enumerate(value)]
    return list(dict.fromkeys(values))


def _retrieval_hits(value: Any, description: str) -> list[dict[str, str | None]]:
    """校验运行结果中的子命中 ID、模型上下文和可选父块 ID。"""

    if not isinstance(value, list):
        raise InputError(f"{description} 必须是 JSON 数组")
    hits: list[dict[str, str | None]] = []
    for index, item in enumerate(value):
        hit = _object(item, f"{description}[{index}]")
        parent = hit.get("parent_chunk_id")
        if isinstance(parent, str) and not parent.strip():
            parent = None
        elif parent is not None:
            parent = _string(parent, f"{description}[{index}].parent_chunk_id")
        hits.append(
            {
                "retrieval_hit_id": _string(
                    hit.get("retrieval_hit_id"),
                    f"{description}[{index}].retrieval_hit_id",
                ),
                "retrieved_context": _string(
                    hit.get("retrieved_context"),
                    f"{description}[{index}].retrieved_context",
                ),
                "parent_chunk_id": parent,
            }
        )
    return hits


def read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    """读取非空 JSONL 行，解析错误中不暴露行内容。"""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise InputError(f"无法读取 {path}：{error}") from error

    rows: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rows.append(_object(json.loads(line), f"{path}:{line_number}"))
        except json.JSONDecodeError as error:
            raise InputError(f"{path}:{line_number} 不是有效 JSON") from error
    if not rows:
        raise InputError(f"{path} 不包含 JSONL 行")
    return rows


def index_chunk_parents(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """将清单中的子 chunk ID 映射到父上下文 ID；无父块时映射到自身。"""

    parents: dict[str, str] = {}
    for line_number, row in enumerate(rows, start=1):
        chunk_id = _string(row.get("chunk_id"), f"chunk 清单第 {line_number} 行的 chunk_id")
        if chunk_id in parents:
            raise InputError(f"chunk 清单包含重复的 chunk_id {chunk_id!r}")
        parent = row.get("parent_chunk_id")
        if isinstance(parent, str) and not parent.strip():
            parent = None
        elif parent is not None:
            parent = _string(parent, f"chunk 清单第 {line_number} 行的 parent_chunk_id")
        parents[chunk_id] = parent or chunk_id
    return parents


def index_dataset(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """校验已标注检索案例，并按唯一案例 ID 建立索引。"""

    cases: dict[str, dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=1):
        case_id = _string(row.get("case_id"), f"数据集第 {line_number} 行的 case_id")
        if case_id in cases:
            raise InputError(f"数据集包含重复的 case_id {case_id!r}")
        knowledge_base = _string(
            row.get("knowledge_base"),
            f"数据集第 {line_number} 行的 knowledge_base",
        )
        if knowledge_base not in {"form", "list", "js"}:
            raise InputError(
                f"数据集第 {line_number} 行的 knowledge_base 必须是 form、list 或 js"
            )
        search_knowledge_bases_value = row.get("search_knowledge_bases")
        if search_knowledge_bases_value is None:
            search_knowledge_bases = [knowledge_base]
        else:
            search_knowledge_bases = _string_list(
                search_knowledge_bases_value,
                f"数据集第 {line_number} 行的 search_knowledge_bases",
            )
        unknown_search_knowledge_bases = sorted(
            set(search_knowledge_bases) - {"form", "list", "js"}
        )
        if unknown_search_knowledge_bases:
            raise InputError(
                f"数据集第 {line_number} 行的 search_knowledge_bases 包含未知知识库："
                + ", ".join(unknown_search_knowledge_bases)
            )
        if knowledge_base not in search_knowledge_bases:
            raise InputError(
                f"数据集第 {line_number} 行的 search_knowledge_bases 必须包含目标知识库"
            )
        if len(search_knowledge_bases) != 1:
            raise InputError(
                f"数据集第 {line_number} 行必须只搜索一个知识库；"
                "跨库案例不属于当前单工具评测"
            )
        target_knowledge_bases = _string_list(
            row.get("target_knowledge_bases", [knowledge_base]),
            f"数据集第 {line_number} 行的 target_knowledge_bases",
        )
        if not set(target_knowledge_bases).issubset(set(search_knowledge_bases)):
            raise InputError(
                f"数据集第 {line_number} 行的 target_knowledge_bases 必须属于搜索范围"
            )
        if len(target_knowledge_bases) != 1:
            raise InputError(
                f"数据集第 {line_number} 行必须只包含一个目标知识库；"
                "跨库案例不属于当前单工具评测"
            )
        query = _string(row.get("query"), f"数据集第 {line_number} 行的 query")
        references = _string_list(
            row.get("reference_context_ids"),
            f"数据集第 {line_number} 行的 reference_context_ids",
        )
        if not references:
            raise InputError(f"数据集第 {line_number} 行的 reference_context_ids 不能为空")
        case = {
            "case_id": case_id,
            "knowledge_base": knowledge_base,
            "search_knowledge_bases": search_knowledge_bases,
            "target_knowledge_bases": target_knowledge_bases,
            "query": query,
            "reference_context_ids": references,
        }
        for field in ("route_group", "query_type"):
            value = row.get(field)
            if value is not None:
                case[field] = _string(value, f"数据集第 {line_number} 行的 {field}")
        cases[case_id] = case
    return cases


def index_run(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """校验检索运行结果，并按唯一案例 ID 建立索引。"""

    runs: dict[str, dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=1):
        case_id = _string(row.get("case_id"), f"运行结果第 {line_number} 行的 case_id")
        if case_id in runs:
            raise InputError(f"运行结果包含重复的 case_id {case_id!r}")
        status = _string(row.get("status"), f"运行结果第 {line_number} 行的 status")
        error = row.get("error")
        if error is not None and not isinstance(error, str):
            raise InputError(f"运行结果第 {line_number} 行的 error 必须是字符串或 null")
        legacy_hits = row.get("retrieval_hits")
        run = {
            "case_id": case_id,
            "status": status,
            "error": error,
            "retrieval_hits": (
                _retrieval_hits(
                    legacy_hits,
                    f"运行结果第 {line_number} 行的 retrieval_hits",
                )
                if legacy_hits is not None
                else []
            ),
        }
        for field in ("candidate_retrieval_hits", "final_retrieval_hits"):
            if row.get(field) is not None:
                run[field] = _retrieval_hits(
                    row[field],
                    f"运行结果第 {line_number} 行的 {field}",
                )
        if "candidate_retrieval_hits" not in run:
            run["candidate_retrieval_hits"] = run["retrieval_hits"]
        if "final_retrieval_hits" not in run:
            run["final_retrieval_hits"] = run["retrieval_hits"]
        if row.get("search_knowledge_bases") is not None:
            run["search_knowledge_bases"] = _string_list(
                row["search_knowledge_bases"],
                f"运行结果第 {line_number} 行的 search_knowledge_bases",
            )
        if row.get("target_knowledge_bases") is not None:
            run["target_knowledge_bases"] = _string_list(
                row["target_knowledge_bases"],
                f"运行结果第 {line_number} 行的 target_knowledge_bases",
            )
        runs[case_id] = run
    return runs


def score_case(
    case: Mapping[str, Any],
    run: Mapping[str, Any],
    chunk_parent_ids: Mapping[str, str],
) -> dict[str, Any]:
    """评估一个已完成案例；检索未完成时报告为不可评分。"""

    references = set(case["reference_context_ids"])
    candidate_hits = run.get("candidate_retrieval_hits", run.get("retrieval_hits", []))
    final_hits = run.get("final_retrieval_hits", run.get("retrieval_hits", []))
    candidate_retrieved = {str(hit["retrieval_hit_id"]) for hit in candidate_hits}
    final_retrieved = {str(hit["retrieval_hit_id"]) for hit in final_hits}
    missing_inventory_ids = sorted(references - set(chunk_parent_ids))
    if missing_inventory_ids:
        raise InputError(
            f"案例 {case['case_id']!r} 引用了清单中不存在的 chunk ID："
            + ", ".join(missing_inventory_ids)
        )
    reference_parents = {chunk_parent_ids[chunk_id] for chunk_id in references}
    def parent_for_hit(hit: Mapping[str, Any]) -> str:
        return str(
            hit["parent_chunk_id"]
            or chunk_parent_ids.get(str(hit["retrieval_hit_id"]), hit["retrieval_hit_id"])
        )

    candidate_parents = {parent_for_hit(hit) for hit in candidate_hits}
    final_parents = {parent_for_hit(hit) for hit in final_hits}
    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "knowledge_base": case["knowledge_base"],
        "search_knowledge_bases": list(
            case.get("search_knowledge_bases", [case["knowledge_base"]])
        ),
        "target_knowledge_bases": list(
            case.get("target_knowledge_bases", [case["knowledge_base"]])
        ),
        "status": run["status"],
        "reference_context_ids": sorted(references),
        "candidate_retrieval_hit_ids": sorted(candidate_retrieved),
        "final_retrieval_hit_ids": sorted(final_retrieved),
        "retrieval_hit_ids": sorted(final_retrieved),
        "reference_parent_context_ids": sorted(reference_parents),
        "candidate_parent_context_ids": sorted(candidate_parents),
        "final_parent_context_ids": sorted(final_parents),
        "retrieval_parent_context_ids": sorted(final_parents),
        "retrieval_hit_audit": [
            {
                "retrieval_hit_id": hit["retrieval_hit_id"],
                "parent_chunk_id": hit["parent_chunk_id"],
            }
            for hit in final_hits
        ],
    }
    for field in ("route_group", "query_type"):
        if field in case:
            result[field] = case[field]
    if run["status"] != "completed":
        result.update(
            {
                "scored": False,
                "unscored_reason": run["error"] or f"运行状态为 {run['status']!r}",
            }
        )
        return result

    candidate_hits_set = references & candidate_retrieved
    candidate_parent_hits = reference_parents & candidate_parents
    final_parent_hits = reference_parents & final_parents
    result.update(
        {
            "scored": True,
            "candidate_hit_context_ids": sorted(candidate_hits_set),
            "candidate_missing_context_ids": sorted(references - candidate_retrieved),
            "candidate_unexpected_context_ids": sorted(candidate_retrieved - references),
            "candidate_recall": len(candidate_hits_set) / len(references),
            "candidate_parent_hit_context_ids": sorted(candidate_parent_hits),
            "candidate_missing_parent_context_ids": sorted(reference_parents - candidate_parents),
            "candidate_unexpected_parent_context_ids": sorted(candidate_parents - reference_parents),
            "candidate_parent_recall": len(candidate_parent_hits) / len(reference_parents),
            "final_parent_hit_context_ids": sorted(final_parent_hits),
            "final_missing_parent_context_ids": sorted(reference_parents - final_parents),
            "final_unexpected_parent_context_ids": sorted(final_parents - reference_parents),
            "final_parent_precision": (
                len(final_parent_hits) / len(final_parents) if final_parents else 0.0
            ),
            # 兼容旧报告字段：Recall 来自候选集，父块 Precision 来自最终上下文。
            "hit_context_ids": sorted(candidate_hits_set),
            "missing_context_ids": sorted(references - candidate_retrieved),
            "unexpected_context_ids": sorted(candidate_retrieved - references),
            "recall": len(candidate_hits_set) / len(references),
            "precision": 0.0,
            "parent_hit_context_ids": sorted(candidate_parent_hits),
            "missing_parent_context_ids": sorted(reference_parents - candidate_parents),
            "unexpected_parent_context_ids": sorted(candidate_parents - reference_parents),
            "parent_recall": len(candidate_parent_hits) / len(reference_parents),
            "parent_precision": (
                len(final_parent_hits) / len(final_parents) if final_parents else 0.0
            ),
        }
    )
    return result


def _metric_summary(
    scores: list[Mapping[str, Any]],
    *,
    score_key: str,
) -> dict[str, Any]:
    """汇总单个检索指标，避免混合不同阶段的分子和分母。"""

    scored = [score for score in scores if score["scored"]]
    return {
        "case_count": len(scores),
        "scored_case_count": len(scored),
        "unscored_case_count": len(scores) - len(scored),
        "macro_score": (
            sum(float(score[score_key]) for score in scored) / len(scored)
            if scored
            else None
        ),
    }


def _metric_set(scores: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """构造本基准的三项阶段化指标。"""

    return {
        "child_recall": _metric_summary(scores, score_key="candidate_recall"),
        "parent_recall": _metric_summary(
            scores, score_key="candidate_parent_recall"
        ),
        "parent_precision": _metric_summary(
            scores, score_key="final_parent_precision"
        ),
    }


def build_report(
    cases: Mapping[str, Mapping[str, Any]],
    runs: Mapping[str, Mapping[str, Any]],
    chunk_parent_ids: Mapping[str, str],
    *,
    dataset_path: str,
    run_path: str,
    min_recall: float | None = None,
    min_precision: float | None = None,
    min_parent_recall: float | None = None,
) -> dict[str, Any]:
    """根据已校验的数据集和运行结果生成可序列化的检索报告。"""

    missing_runs = sorted(set(cases) - set(runs))
    extra_runs = sorted(set(runs) - set(cases))
    if missing_runs:
        raise InputError(f"运行结果缺少 case_id：{', '.join(missing_runs)}")
    if extra_runs:
        raise InputError(f"运行结果包含未知 case_id：{', '.join(extra_runs)}")

    for case_id, case in cases.items():
        expected_scope = list(
            case.get("search_knowledge_bases", [case["knowledge_base"]])
        )
        actual_scope = runs[case_id].get("search_knowledge_bases")
        if actual_scope is None:
            if len(expected_scope) != 1:
                raise InputError(f"运行结果案例 {case_id!r} 缺少单库搜索范围")
        elif list(actual_scope) != expected_scope:
            raise InputError(
                f"运行结果案例 {case_id!r} 的搜索范围与数据集不一致"
            )
        expected_targets = list(
            case.get("target_knowledge_bases", [case["knowledge_base"]])
        )
        actual_targets = runs[case_id].get("target_knowledge_bases")
        if actual_targets is not None and list(actual_targets) != expected_targets:
            raise InputError(
                f"运行结果案例 {case_id!r} 的目标知识库与数据集不一致"
            )

    scores = [
        score_case(
            cases[case_id],
            runs[case_id],
            chunk_parent_ids,
        )
        for case_id in sorted(cases)
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    route_grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for score in scores:
        grouped[str(score["knowledge_base"])].append(score)
        route_grouped[str(score.get("route_group", score["knowledge_base"]))].append(score)

    report: dict[str, Any] = {
        "format": "xingyun-rag-retrieval-report/v1",
        "dataset": {"path": dataset_path, "case_count": len(cases)},
        "run": {"path": run_path, "case_count": len(runs)},
        "chunk_inventory": {"chunk_count": len(chunk_parent_ids)},
        "metrics": _metric_set(scores),
        "knowledge_bases": {
            knowledge_base: _metric_set(grouped[knowledge_base])
            for knowledge_base in sorted(grouped)
        },
        "route_groups": {
            route_group: _metric_set(route_scores)
            for route_group, route_scores in sorted(route_grouped.items())
        },
        "cases": scores,
        "thresholds": {
            "min_recall": min_recall,
            "min_precision": min_precision,
            "min_parent_recall": min_parent_recall,
        },
    }
    report["violations"] = threshold_violations(report)
    return report


def threshold_violations(report: Mapping[str, Any]) -> list[str]:
    """从带有可选阈值的报告中返回可读的阈值失败信息。"""

    thresholds = _object(report["thresholds"], "report.thresholds")
    minimum_recall = thresholds.get("min_recall")
    minimum_precision = thresholds.get("min_precision")
    minimum_parent_recall = thresholds.get("min_parent_recall")
    violations: list[str] = []
    metric_sets = [("overall", report["metrics"]), *_object(
        report["knowledge_bases"], "report.knowledge_bases"
    ).items()]
    for name, metric_set in metric_sets:
        metrics = _object(metric_set, f"report metrics for {name}")
        child_recall = _object(metrics["child_recall"], f"child recall for {name}")["macro_score"]
        parent_recall = _object(metrics["parent_recall"], f"parent recall for {name}")["macro_score"]
        parent_precision = _object(metrics["parent_precision"], f"parent precision for {name}")["macro_score"]
        if minimum_recall is not None and (
            child_recall is None or float(child_recall) < float(minimum_recall)
        ):
            violations.append(f"{name} 子块 Recall 低于 {minimum_recall}")
        if minimum_precision is not None and (
            parent_precision is None or float(parent_precision) < float(minimum_precision)
        ):
            violations.append(f"{name} 父块 Precision 低于 {minimum_precision}")
        if minimum_parent_recall is not None and (
            parent_recall is None or float(parent_recall) < float(minimum_parent_recall)
        ):
            violations.append(f"{name} 父块 Recall 低于 {minimum_parent_recall}")
    return violations


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    """写入 UTF-8 JSON 报告，必要时创建父目录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _percentage(value: Any) -> str:
    if value is None:
        return "不适用"
    return f"{float(value):.2%}"


def print_summary(report: Mapping[str, Any]) -> None:
    """打印简洁报告摘要，不打印检索上下文内容。"""

    metrics = _object(report["metrics"], "report.metrics")
    child_recall = _object(metrics["child_recall"], "report child_recall")
    parent_recall = _object(metrics["parent_recall"], "report parent_recall")
    parent_precision = _object(metrics["parent_precision"], "report parent_precision")
    print(
        "子块总体："
        f"Recall={_percentage(child_recall['macro_score'])} "
        f"已评分={child_recall['scored_case_count']}/{child_recall['case_count']}"
    )
    print(
        "父块总体："
        f"Recall={_percentage(parent_recall['macro_score'])} "
        f"Precision={_percentage(parent_precision['macro_score'])} "
        f"已评分={parent_recall['scored_case_count']}/{parent_recall['case_count']}"
    )
    for name, group in _object(report["knowledge_bases"], "report.knowledge_bases").items():
        group_metrics = _object(group, f"知识库 {name}")
        group_child_recall = _object(group_metrics["child_recall"], f"子块 {name}")
        group_parent_recall = _object(group_metrics["parent_recall"], f"父块 Recall {name}")
        group_parent_precision = _object(group_metrics["parent_precision"], f"父块 Precision {name}")
        print(
            f"子块 {name}："
            f"Recall={_percentage(group_child_recall['macro_score'])} "
            f"已评分={group_child_recall['scored_case_count']}/{group_child_recall['case_count']}"
        )
        print(
            f"父块 {name}："
            f"Recall={_percentage(group_parent_recall['macro_score'])} "
            f"Precision={_percentage(group_parent_precision['macro_score'])} "
            f"已评分={group_parent_recall['scored_case_count']}/{group_parent_recall['case_count']}"
        )
    for name, group in _object(report["route_groups"], "report.route_groups").items():
        group_metrics = _object(group, f"路由 {name}")
        group_child_recall = _object(group_metrics["child_recall"], f"路由子块 {name}")
        group_parent_recall = _object(group_metrics["parent_recall"], f"路由父块 Recall {name}")
        group_parent_precision = _object(group_metrics["parent_precision"], f"路由父块 Precision {name}")
        print(
            f"路由 {name}："
            f"子块 Recall={_percentage(group_child_recall['macro_score'])} "
            f"父块 Recall={_percentage(group_parent_recall['macro_score'])} "
            f"父块 Precision={_percentage(group_parent_precision['macro_score'])} "
            f"已评分={group_child_recall['scored_case_count']}/{group_child_recall['case_count']}"
        )


def _threshold(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("阈值必须是 0 到 1 之间的数字") from error
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("阈值必须是 0 到 1 之间的数字")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """构建检索评分命令行解析器。"""

    parser = argparse.ArgumentParser(
        description="根据已标注数据集评估 WeKnora 原始 chunk ID。"
    )
    parser.add_argument("--dataset", type=Path, required=True, help="已标注的检索 JSONL。")
    parser.add_argument("--run", type=Path, required=True, help="实际检索结果 JSONL。")
    parser.add_argument(
        "--chunk-inventory",
        type=Path,
        default=Path("datasets/chunks.v1.jsonl"),
        help="用于将参考子 chunk 映射到父上下文的 chunk 清单。",
    )
    parser.add_argument("--out", type=Path, required=True, help="输出报告 JSON 路径。")
    parser.add_argument("--min-recall", type=_threshold, help="可选的子块 Recall 阈值。")
    parser.add_argument(
        "--min-precision",
        type=_threshold,
        help="可选的父块 Precision 阈值。",
    )
    parser.add_argument(
        "--min-parent-recall",
        type=_threshold,
        help="可选的父块 Recall 阈值。",
    )
    parser.add_argument(
        "--fail-on-unscored",
        action="store_true",
        help="存在未完成案例时返回非零状态。",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """读取输入并写入报告，按阈值返回退出状态。"""

    dataset_rows = read_jsonl(args.dataset)
    run_rows = read_jsonl(args.run)
    inventory_rows = read_jsonl(args.chunk_inventory)
    report = build_report(
        index_dataset(dataset_rows),
        index_run(run_rows),
        index_chunk_parents(inventory_rows),
        dataset_path=str(args.dataset),
        run_path=str(args.run),
        min_recall=args.min_recall,
        min_precision=args.min_precision,
        min_parent_recall=args.min_parent_recall,
    )
    write_report(args.out, report)
    print_summary(report)
    print(f"已将报告写入 {args.out}")
    if report["violations"]:
        for violation in report["violations"]:
            print(f"阈值未通过：{violation}", file=sys.stderr)
        return 1
    if args.fail_on_unscored and report["metrics"]["child_recall"]["unscored_case_count"]:
        print("不允许存在未评分案例", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """运行检索评分器；输入格式错误时返回 2。"""

    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except InputError as error:
        print(f"score_retrieval：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
