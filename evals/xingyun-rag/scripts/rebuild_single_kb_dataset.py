"""从现有标注集中生成单知识库检索数据集。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


SINGLE_ROUTES = {"form-single", "list-single", "js-single"}
KNOWLEDGE_BASES = {"form", "list", "js"}


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


def rebuild(
    source_rows: list[Mapping[str, Any]],
    inventory_rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """删除跨库路由，并按当前 chunk 清单校验和保留引用 ID。"""

    inventory: dict[str, str] = {}
    for row in inventory_rows:
        chunk_id = row.get("chunk_id")
        knowledge_base = row.get("knowledge_base")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError("chunk 清单包含空 chunk_id")
        if knowledge_base not in KNOWLEDGE_BASES:
            raise ValueError(f"chunk {chunk_id!r} 的 knowledge_base 无效")
        inventory[chunk_id] = str(knowledge_base)

    output: list[dict[str, Any]] = []
    for row in source_rows:
        route = row.get("route_group")
        if route not in SINGLE_ROUTES:
            continue
        knowledge_base = row.get("knowledge_base")
        if knowledge_base not in KNOWLEDGE_BASES:
            raise ValueError(f"案例 {row.get('case_id')!r} 的 knowledge_base 无效")
        references = row.get("reference_context_ids")
        if not isinstance(references, list) or not references:
            raise ValueError(f"案例 {row.get('case_id')!r} 没有 reference_context_ids")
        for chunk_id in references:
            if not isinstance(chunk_id, str) or inventory.get(chunk_id) != knowledge_base:
                raise ValueError(
                    f"案例 {row.get('case_id')!r} 的参考 chunk {chunk_id!r} "
                    "不在当前目标知识库清单中；请先重新人工标注"
                )

        rebuilt = dict(row)
        rebuilt["search_knowledge_bases"] = [knowledge_base]
        rebuilt["target_knowledge_bases"] = [knowledge_base]
        output.append(rebuilt)

    expected = {"form-single": 30, "list-single": 30, "js-single": 60}
    counts = {route: sum(row.get("route_group") == route for row in output) for route in expected}
    if counts != expected:
        raise ValueError(f"单库数据集数量不符合预期：{counts}，预期：{expected}")
    return output


def write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    """按一行一个 JSON 对象写出数据集。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    """生成并校验 120 条单知识库数据集。"""

    parser = argparse.ArgumentParser(description="生成单知识库星云检索数据集")
    parser.add_argument("--source", type=Path, required=True, help="原始标注 JSONL")
    parser.add_argument("--inventory", type=Path, required=True, help="当前 chunk 清单")
    parser.add_argument("--out", type=Path, required=True, help="单知识库数据集输出路径")
    args = parser.parse_args()
    rows = rebuild(read_jsonl(args.source), read_jsonl(args.inventory))
    write_jsonl(args.out, rows)
    print(f"已生成 {len(rows)} 个单知识库案例：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
