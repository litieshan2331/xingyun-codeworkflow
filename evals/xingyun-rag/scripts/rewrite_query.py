"""使用与 WeKnora 查询理解阶段一致的规则改写检索问题。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI


DEFAULT_REWRITE_MODEL = "Qwen/Qwen3.6-27B-FP8"

# WeKnora 的 default_rewrite 模板要求保留专有名词和检索词，并输出结构化 JSON。
# 阶段一没有会话历史、图片或附件，因此只提供这些输入标记。
REWRITE_SYSTEM_PROMPT = """你是负责查询理解的智能助手。请完成两项任务：
1. 将用户问题改写成可以独立检索的完整问题，消解指代并补全省略信息。
2. 判断问题意图。

改写规则：
- 保留用户提到的组件名、字段名、函数名、API 名和技术术语，不得丢失具体检索词。
- 改写结果必须保持原意，是一个不超过 30 个词的中文问题。
- 不要生成“请在知识库中查找”“请搜索”等元指令，直接保留要检索的事实和关键词。
- 没有上下文可补全时，尽量保持原问题不变。

意图只能从以下值中选择：greeting、summarize、web_search、kb_search、clarification、follow_up、image_only、doc_only、chitchat。涉及知识库、文档、文件或技术资料时使用 kb_search；无法确定时使用 kb_search。

必须只输出一个 JSON 对象，不要输出 Markdown、代码围栏或解释：
{"rewrite_query":"string","intent":"string","image_description":""}"""

REWRITE_USER_PROMPT = """[运行时上下文]
当前问题没有对话历史、图片或附件。

## 用户问题
{query}

## JSON 输出"""


class ChatCompletionClient(Protocol):
    """查询改写所需的 OpenAI 兼容客户端接口。"""

    @property
    def chat(self) -> Any: ...


@dataclass(frozen=True)
class RewriteResult:
    """一次改写的结果及可审计状态。"""

    query: str
    applied: bool
    error: str | None = None


def _extract_json(content: str) -> dict[str, Any] | None:
    """解析模型输出，兼容偶发的代码围栏或额外文本。"""

    candidate = content.strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_rewrite_response(content: str, original_query: str) -> RewriteResult:
    """从 WeKnora 兼容的结构化响应中提取改写问题。"""

    parsed = _extract_json(content)
    if parsed is None:
        return RewriteResult(original_query, False, "改写模型返回的内容不是有效 JSON")
    rewritten = parsed.get("rewrite_query")
    if not isinstance(rewritten, str) or not rewritten.strip():
        return RewriteResult(original_query, False, "改写响应缺少非空 rewrite_query")
    normalized = re.sub(r"\s+", " ", rewritten).strip()
    return RewriteResult(normalized, normalized != original_query.strip())


class QueryRewriter:
    """调用 OpenAI 兼容模型执行 WeKnora 风格的查询改写。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = DEFAULT_REWRITE_MODEL,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._model = model
        self._client = OpenAI(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            timeout=timeout_seconds,
        )

    def rewrite(self, query: str) -> RewriteResult:
        """改写问题；模型或解析失败时回退原问题。"""

        original = query.strip()
        if not original:
            return RewriteResult(query, False, "原问题为空")
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": REWRITE_USER_PROMPT.format(query=original),
                    },
                ],
                temperature=0.3,
                max_tokens=150,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            content = response.choices[0].message.content
            if not isinstance(content, str):
                return RewriteResult(original, False, "改写模型没有返回文本")
            return parse_rewrite_response(content, original)
        except Exception as error:  # noqa: BLE001 - 与 WeKnora 一样回退原问题
            return RewriteResult(original, False, f"改写调用失败：{error}")
