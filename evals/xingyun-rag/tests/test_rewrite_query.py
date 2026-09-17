"""WeKnora 风格查询改写的解析测试。"""

from __future__ import annotations

from scripts.rewrite_query import parse_rewrite_response


def test_parse_rewrite_response_uses_rewritten_query() -> None:
    result = parse_rewrite_response(
        '{"rewrite_query":"Stylefile 的 bordered 默认值是什么？","intent":"kb_search","image_description":""}',
        "它默认是什么？",
    )

    assert result.query == "Stylefile 的 bordered 默认值是什么？"
    assert result.applied is True
    assert result.error is None


def test_parse_rewrite_response_keeps_original_query_when_json_is_invalid() -> None:
    result = parse_rewrite_response("不是 JSON", "Stylefile 的默认值是什么？")

    assert result.query == "Stylefile 的默认值是什么？"
    assert result.applied is False
    assert result.error == "改写模型返回的内容不是有效 JSON"


def test_parse_rewrite_response_normalizes_whitespace() -> None:
    result = parse_rewrite_response(
        '{"rewrite_query":"Stylefile   的\\n bordered 默认值是什么？"}',
        "Stylefile 的 bordered 默认值是什么？",
    )

    assert result.query == "Stylefile 的 bordered 默认值是什么？"
    assert result.applied is False
