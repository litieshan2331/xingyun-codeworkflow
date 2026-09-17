"""根据当前参考 chunk 的章节和 API 名称刷新单库测试问题。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

SINGLE_ROUTES = {"form-single", "list-single", "js-single"}
QUERY_OVERRIDES = {
    "js-single-042": "在星云 JS 增强的新增表单场景中，如何使用 _form.getFieldsValue、_form.setFieldsValue 和 saveFormAgo 完成取值、校验与保存？",
    "js-single-047": "在星云流程节点发送场景中，如何结合 _flow.setNextFlowData、_flow.setSendParams 和 _flow.sendBtnAfter 传递参数并处理成功回调？",
    "js-single-050": "在星云 JS 增强中，如何把 Markdown 自定义按钮、动态字段校验和 Archiving 归档操作串成一条处理链？",
    "js-single-048": "在星云 JS 增强的编辑表单场景中，如何用 _form.readyValue 回显数据，再通过 onValuesChange 和 saveFormAfter 完成保存？",
    "js-single-053": "在星云流程弹窗场景中，如何根据 processInfo 组装 sendingAgo 参数，并在 sendBtnAfter 中确认发送结果？",
    "js-single-056": "在星云 JS 增强中，如何先用 Markdown 输入控件收集字段，再执行权限校验和 Archiving 归档？",
}
IDENTIFIER_PATTERN = re.compile(r"(?:this|_this|_rootThis|_form|_flow|_tool)\.[A-Za-z_$][A-Za-z0-9_$]*|\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{2,4}\s+(.+?)\s*$")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 对象。"""
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
        rows.append(value)
    return rows


def compact(value: str, limit: int = 28) -> str:
    """压缩主题文本，避免问题过长。"""
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def terms_for_chunks(references: list[str], inventory: Mapping[str, Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """从参考 chunk 提取章节标题和可检索 API 名称。"""
    headings: list[str] = []
    identifiers: list[str] = []
    for chunk_id in references:
        row = inventory.get(chunk_id)
        if row is None:
            raise ValueError(f"参考 chunk 不在当前清单中：{chunk_id}")
        content = str(row.get("content", ""))
        for line in content.splitlines():
            match = HEADING_PATTERN.match(line)
            if match:
                heading = re.sub(r"[*`#]", "", match.group(1)).strip()
                if heading and heading not in headings:
                    headings.append(heading)
        for identifier in IDENTIFIER_PATTERN.findall(content):
            if identifier not in identifiers:
                identifiers.append(identifier)
    return headings, identifiers


def topic_for_chunk(row: Mapping[str, Any]) -> str:
    """提取适合自然语言问题的具体主题短语。"""
    content = str(row.get("content", ""))
    for line in content.splitlines():
        stripped = re.sub(r"[`*_>#|]", "", line).strip(" -:：")
        if stripped and len(stripped) >= 4 and not set(stripped) <= {"-", "="}:
            return compact(stripped, 30)
    return "该分块的具体配置规则"


def rewrite_query(row: Mapping[str, Any], inventory: Mapping[str, Mapping[str, Any]]) -> str:
    """为单库案例生成包含具体章节/API 的自然语言问题。"""
    case_id = str(row["case_id"])
    if case_id in QUERY_OVERRIDES:
        return QUERY_OVERRIDES[case_id]
    refs = [str(item) for item in row["reference_context_ids"]]
    headings, identifiers = terms_for_chunks(refs, inventory)
    topic = topic_for_chunk(inventory[refs[0]])
    route = str(row["route_group"])
    category = str(row.get("query_type", "single_fact"))
    number = int(str(row["case_id"]).rsplit("-", 1)[-1])
    if route == "js-single" and category == "multi_hop":
        terms = identifiers[:6] or headings[:4]
        angles = ["初始化状态、读取参数并更新结果", "表单取值、校验后保存并处理回调", "流程发送、节点参数传递和成功回调", "工具请求、时间处理和用户提示", "列表渲染、列编辑和保存数据", "异常分支、权限控制和返回值"]
        forms = ["请设计完整处理步骤", "请说明先后调用关系", "请梳理参数如何流转", "请说明成功和失败分支", "请说明回调之间的衔接", "请给出实现时的注意点"]
        return "在星云 JS 增强中，围绕" + compact(topic, 24) + "，" + forms[(number - 41) % len(forms)] + "：如何" + angles[(number - 41) % len(angles)] + "，并按顺序使用 " + "、".join(compact(term) for term in terms) + "？"
    terms = identifiers[:3] or headings[:2]
    prefix = "星云 JS 增强" if route == "js-single" else "星云知识库"
    aspects = ["基本含义和适用场景", "必填参数及其数据类型", "默认值与配置限制", "调用时机和回调参数", "返回值及后续处理", "与相邻配置的区别", "典型配置示例", "异常情况处理", "字段之间的关系", "生成时的约束", "可选参数差异", "实际使用步骤"]
    forms = ["请说明", "请解释", "请梳理", "请总结", "请明确", "请分析"]
    subject = "、".join(compact(term) for term in terms) or topic
    return f"根据{prefix}，{forms[(number - 1) % len(forms)]} {subject} 的{aspects[(number - 1) % len(aspects)]}，并给出使用注意事项？"


def refresh(rows: list[dict[str, Any]], inventory_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """刷新单库案例问题并再次校验参考 ID 与知识库一致。"""
    inventory = {str(row["chunk_id"]): row for row in inventory_rows}
    output: list[dict[str, Any]] = []
    for row in rows:
        if row.get("route_group") not in SINGLE_ROUTES:
            continue
        rebuilt = dict(row)
        rebuilt["search_knowledge_bases"] = [str(row["knowledge_base"])]
        rebuilt["target_knowledge_bases"] = [str(row["knowledge_base"])]
        rebuilt["query"] = rewrite_query(row, inventory)
        output.append(rebuilt)
    return output


def main() -> int:
    """刷新并写出 120 条单知识库数据集。"""
    parser = argparse.ArgumentParser(description="刷新单库测试问题")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = refresh(read_jsonl(args.dataset), read_jsonl(args.inventory))
    if len(rows) != 120:
        raise ValueError(f"刷新后案例数为 {len(rows)}，预期 120")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    print(f"已刷新 {len(rows)} 个单知识库案例：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
