from __future__ import annotations

import pytest

from wecom_feishu_router.config import RouteConfig
from wecom_feishu_router.errors import RouterError
from wecom_feishu_router.translator import text_payload


def route() -> RouteConfig:
    return RouteConfig(
        "https://open.feishu.test/hook",
        mention_map={"mapped": "ou_123"},
    )


def test_null_text_is_rejected() -> None:
    with pytest.raises(RouterError, match="必须是非空字符串"):
        text_payload(
            {"msgtype": "text", "text": {"content": None}},
            route(),
        )


def test_unmapped_mention_remains_visible_and_duplicates_are_removed() -> None:
    result = text_payload(
        {
            "msgtype": "text",
            "text": {
                "content": "告警",
                "mentioned_list": ["mapped", "unmapped", "unmapped"],
            },
        },
        route(),
    )

    assert result["content"]["text"] == (
        '<at user_id="ou_123">mapped</at> @unmapped\n告警'
    )


def test_news_preserves_picture_url() -> None:
    result = text_payload(
        {
            "msgtype": "news",
            "news": {
                "articles": [
                    {
                        "title": "标题",
                        "description": "描述",
                        "url": "https://example.test/article",
                        "picurl": "https://example.test/image.png",
                    }
                ]
            },
        },
        route(),
    )

    assert result["content"]["text"].splitlines() == [
        "标题",
        "描述",
        "https://example.test/article",
        "https://example.test/image.png",
    ]


def test_template_card_preserves_key_text_and_actions() -> None:
    result = text_payload(
        {
            "msgtype": "template_card",
            "template_card": {
                "source": {"desc": "监控平台"},
                "main_title": {"title": "服务异常", "desc": "订单服务"},
                "emphasis_content": {"title": "95%", "desc": "错误率"},
                "sub_title_text": "请立即处理",
                "quote_area": {
                    "title": "最近错误",
                    "quote_text": "connection refused",
                },
                "vertical_content_list": [{"title": "区域", "desc": "华东一区"}],
                "horizontal_content_list": [{"keyname": "负责人", "value": "张三"}],
                "jump_list": [
                    {"title": "查看监控", "url": "https://example.test/monitor"}
                ],
                "card_action": {"url": "https://example.test/action"},
            },
        },
        route(),
    )
    text = result["content"]["text"]

    for expected in (
        "监控平台",
        "服务异常",
        "订单服务",
        "95%",
        "错误率",
        "请立即处理",
        "最近错误",
        "connection refused",
        "区域",
        "华东一区",
        "负责人：张三",
        "查看监控：https://example.test/monitor",
        "https://example.test/action",
    ):
        assert expected in text
