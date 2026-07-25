from __future__ import annotations

import base64
import hashlib
import html
import json
from typing import Any

from .config import RouteConfig
from .errors import RouterError


def text_payload(payload: dict[str, Any], route: RouteConfig) -> dict[str, Any]:
    msgtype = payload.get("msgtype")
    if msgtype == "text":
        text = _required_content(payload, "text")
        content = _required_text(text, "content", "text")
        mentions = text.get("mentioned_list", [])
        mobile_mentions = text.get("mentioned_mobile_list", [])
        if not isinstance(mentions, list) or not isinstance(mobile_mentions, list):
            raise RouterError("text 的 @ 成员字段必须是数组")
        mentions = [*mentions, *mobile_mentions]
        mention_prefix = _mentions(mentions, route.mention_map)
        return {
            "msg_type": "text",
            "content": {"text": f"{mention_prefix}{content}"},
        }

    if msgtype in {"markdown", "markdown_v2"}:
        content = _required_text(
            _required_content(payload, msgtype), "content", msgtype
        )
        return {"msg_type": "text", "content": {"text": content}}

    if msgtype == "news":
        articles = _required_content(payload, "news").get("articles", [])
        if not isinstance(articles, list) or not articles:
            raise RouterError("news.articles 必须是非空数组")
        blocks = []
        for article in articles:
            if not isinstance(article, dict):
                raise RouterError("news.articles 内容无效")
            title = _optional_text(article.get("title"))
            description = _optional_text(article.get("description"))
            url = _optional_text(article.get("url"))
            pic_url = _optional_text(article.get("picurl"))
            block = "\n".join(
                part for part in (title, description, url, pic_url) if part
            )
            if block:
                blocks.append(block)
        if not blocks:
            raise RouterError("news.articles 不包含可发送内容")
        return {"msg_type": "text", "content": {"text": "\n\n".join(blocks)}}

    if msgtype == "template_card":
        card = _required_content(payload, "template_card")
        summary = _template_card_text(card)
        return {"msg_type": "text", "content": {"text": summary}}

    raise RouterError(f"暂不支持的消息类型: {msgtype!r}")


def decode_image(payload: dict[str, Any], max_bytes: int) -> bytes:
    image = _required_content(payload, "image")
    encoded = image.get("base64")
    if not isinstance(encoded, str) or not encoded:
        raise RouterError("image.base64 不能为空")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise RouterError("image.base64 不是有效的 Base64") from error
    if not content:
        raise RouterError("图片内容为空")
    if len(content) > max_bytes:
        raise RouterError(f"图片超过大小限制 {max_bytes} bytes")

    expected_md5 = image.get("md5")
    if expected_md5:
        actual_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
        if actual_md5.lower() != str(expected_md5).lower():
            raise RouterError("图片 MD5 校验失败")
    return content


def _required_content(payload: dict[str, Any], key: str) -> dict[str, Any]:
    content = payload.get(key)
    if not isinstance(content, dict):
        raise RouterError(f"缺少 {key} 消息体")
    return content


def _required_text(data: dict[str, Any], key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RouterError(f"{section}.{key} 必须是非空字符串")
    return value


def _optional_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _mentions(source_ids: list[Any], mention_map: dict[str, str]) -> str:
    mentions = []
    seen = set()
    for source_id in source_ids:
        source = str(source_id)
        if source in seen:
            continue
        seen.add(source)
        if source == "@all":
            mentions.append('<at user_id="all">所有人</at>')
            continue
        target = mention_map.get(source)
        if target:
            mentions.append(
                f'<at user_id="{html.escape(target, quote=True)}">'
                f"{html.escape(source)}</at>"
            )
        else:
            mentions.append(f"@{source}")
    return (" ".join(mentions) + "\n") if mentions else ""


def _template_card_text(card: dict[str, Any]) -> str:
    parts: list[str] = []

    source = _mapping(card.get("source"))
    _append(parts, source.get("desc"))

    for section_name in ("main_title", "emphasis_content"):
        section = _mapping(card.get(section_name))
        _append(parts, section.get("title"))
        _append(parts, section.get("desc"))

    _append(parts, card.get("sub_title_text"))

    image_text = _mapping(card.get("image_text_area"))
    _append(parts, image_text.get("title"))
    _append(parts, image_text.get("desc"))
    _append(parts, _action_url(image_text))

    quote = _mapping(card.get("quote_area"))
    _append(parts, quote.get("title"))
    _append(parts, quote.get("quote_text"))
    _append(parts, _action_url(quote))

    for item in _mapping_list(card.get("vertical_content_list")):
        _append(parts, item.get("title"))
        _append(parts, item.get("desc"))

    for item in _mapping_list(card.get("horizontal_content_list")):
        label = _optional_text(item.get("keyname"))
        value = _optional_text(item.get("value")) or _action_url(item)
        if label and value:
            _append(parts, f"{label}：{value}")
        else:
            _append(parts, label or value)

    for item in _mapping_list(card.get("jump_list")):
        title = _optional_text(item.get("title"))
        url = _action_url(item)
        if title and url:
            _append(parts, f"{title}：{url}")
        else:
            _append(parts, title or url)

    card_action = _mapping(card.get("card_action"))
    _append(parts, _action_url(card_action))

    card_image = _mapping(card.get("card_image"))
    _append(parts, card_image.get("url"))

    if not parts:
        return json.dumps(card, ensure_ascii=False, separators=(",", ":"))
    return "\n".join(parts)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _action_url(data: dict[str, Any]) -> str:
    for key in ("url", "appurl", "pagepath"):
        value = _optional_text(data.get(key))
        if value:
            return value
    return ""


def _append(parts: list[str], value: Any) -> None:
    text = _optional_text(value)
    if text and text not in parts:
        parts.append(text)
