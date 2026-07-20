"""验证 OpenAI Compatible 流式响应的协议边界。"""

from ac_py.llm.client import OpenAICompatibleClient


def test_stream_parser_ignores_null_content() -> None:
    """思考阶段的 null content 不得被转换成字符串 None。"""

    line = 'data: {"choices":[{"delta":{"content":null,"reasoning_content":"思考"}}]}'
    assert OpenAICompatibleClient._parse_stream_line(line) == ""


def test_stream_parser_returns_text_content() -> None:
    """正文增量应按原文本返回。"""

    line = 'data: {"choices":[{"delta":{"content":"退款处理中"}}]}'
    assert OpenAICompatibleClient._parse_stream_line(line) == "退款处理中"
