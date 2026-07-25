from __future__ import annotations

import base64
import hashlib
import json
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from wecom_feishu_router.config import (
    FeishuAppConfig,
    RouteConfig,
    Settings,
)
from wecom_feishu_router.main import create_app


def settings(tmp_path: Path) -> Settings:
    return Settings(
        routes={
            "ops": RouteConfig(
                webhook_url="https://open.feishu.test/bot/hook",
                chat_id="oc_test",
                mention_map={"zhangsan": "ou_zhangsan"},
            )
        },
        feishu_app=FeishuAppConfig(
            app_id="cli_test",
            app_secret="secret",
            api_base="https://open.feishu.test/open-apis",
        ),
        sqlite_path=tmp_path / "router.db",
    )


async def request_client(
    tmp_path: Path,
    handler: Any,
    app_settings: Settings | None = None,
) -> tuple[httpx.AsyncClient, AsyncExitStack]:
    resources = AsyncExitStack()
    downstream = await resources.enter_async_context(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    app = create_app(app_settings or settings(tmp_path), http_client=downstream)
    await resources.enter_async_context(app.router.lifespan_context(app))
    client = await resources.enter_async_context(
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://router.test",
        )
    )
    return client, resources


@pytest.mark.asyncio
async def test_text_message_is_translated(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client, resources = await request_client(tmp_path, handler)
    try:
        response = await client.post(
            "/cgi-bin/webhook/send?key=ops",
            json={
                "msgtype": "text",
                "text": {
                    "content": "服务恢复",
                    "mentioned_list": ["zhangsan", "@all"],
                },
            },
        )
    finally:
        await resources.aclose()

    assert response.json() == {"errcode": 0, "errmsg": "ok"}
    assert captured == [
        {
            "msg_type": "text",
            "content": {
                "text": (
                    '<at user_id="ou_zhangsan">zhangsan</at> '
                    '<at user_id="all">所有人</at>\n服务恢复'
                )
            },
        }
    ]


@pytest.mark.asyncio
async def test_image_is_uploaded_then_sent_to_webhook(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "t-test",
                    "expire": 7200,
                },
            )
        if request.url.path.endswith("/im/v1/images"):
            assert request.headers["Authorization"] == "Bearer t-test"
            return httpx.Response(
                200, json={"code": 0, "data": {"image_key": "img_test"}}
            )
        body = json.loads(request.content)
        assert body == {
            "msg_type": "image",
            "content": {"image_key": "img_test"},
        }
        return httpx.Response(200, json={"StatusCode": 0, "StatusMessage": "success"})

    image = b"fake png bytes"
    client, resources = await request_client(tmp_path, handler)
    try:
        response = await client.post(
            "/webhook/ops",
            json={
                "msgtype": "image",
                "image": {
                    "base64": base64.b64encode(image).decode(),
                    "md5": hashlib.md5(image, usedforsecurity=False).hexdigest(),
                },
            },
        )
    finally:
        await resources.aclose()

    assert response.json() == {"errcode": 0, "errmsg": "ok"}
    assert [Path(httpx.URL(url).path).name for url in calls] == [
        "internal",
        "images",
        "hook",
    ]


@pytest.mark.asyncio
async def test_file_upload_media_id_can_be_sent(tmp_path: Path) -> None:
    sent_message: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_message
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "t-test",
                    "expire": 7200,
                },
            )
        if request.url.path.endswith("/im/v1/files"):
            return httpx.Response(
                200, json={"code": 0, "data": {"file_key": "file_test"}}
            )
        if request.url.path.endswith("/im/v1/messages"):
            sent_message = json.loads(request.content)
            assert request.url.params["receive_id_type"] == "chat_id"
            return httpx.Response(200, json={"code": 0, "msg": "success"})
        raise AssertionError(f"unexpected request: {request.url}")

    client, resources = await request_client(tmp_path, handler)
    try:
        upload = await client.post(
            "/cgi-bin/webhook/upload_media?key=ops&type=file",
            files={"media": ("report.pdf", b"pdf bytes", "application/pdf")},
        )
        media_id = upload.json()["media_id"]
        send = await client.post(
            "/cgi-bin/webhook/send?key=ops",
            json={"msgtype": "file", "file": {"media_id": media_id}},
        )
    finally:
        await resources.aclose()

    assert upload.json()["errcode"] == 0
    assert send.json() == {"errcode": 0, "errmsg": "ok"}
    assert sent_message == {
        "receive_id": "oc_test",
        "msg_type": "file",
        "content": '{"file_key":"file_test"}',
    }


@pytest.mark.asyncio
async def test_unknown_route_uses_wecom_error_shape(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("downstream must not be called")

    client, resources = await request_client(tmp_path, handler)
    try:
        response = await client.post(
            "/cgi-bin/webhook/send?key=missing",
            json={"msgtype": "text", "text": {"content": "ignored"}},
        )
    finally:
        await resources.aclose()

    assert response.status_code == 200
    assert response.json()["errcode"] == 93000


@pytest.mark.asyncio
async def test_missing_key_uses_wecom_error_shape(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("downstream must not be called")

    client, resources = await request_client(tmp_path, handler)
    try:
        response = await client.post(
            "/cgi-bin/webhook/send",
            json={"msgtype": "text", "text": {"content": "ignored"}},
        )
    finally:
        await resources.aclose()

    assert response.status_code == 200
    assert response.json()["errcode"] == 40008


@pytest.mark.asyncio
async def test_unknown_webhook_response_is_not_reported_as_success(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client, resources = await request_client(tmp_path, handler)
    try:
        response = await client.post(
            "/cgi-bin/webhook/send?key=ops",
            json={"msgtype": "text", "text": {"content": "test"}},
        )
    finally:
        await resources.aclose()

    assert response.json()["errcode"] == 45002


@pytest.mark.asyncio
async def test_request_body_limit_is_enforced(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("downstream must not be called")

    limited = replace(settings(tmp_path), max_request_bytes=100)
    client, resources = await request_client(
        tmp_path,
        handler,
        app_settings=limited,
    )
    try:
        response = await client.post(
            "/cgi-bin/webhook/send?key=ops",
            json={"msgtype": "text", "text": {"content": "x" * 200}},
        )
    finally:
        await resources.aclose()

    assert response.json()["errcode"] == 40006


@pytest.mark.asyncio
async def test_oversized_file_is_rejected_before_feishu_upload(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("downstream must not be called")

    limited = replace(settings(tmp_path), max_file_bytes=4)
    client, resources = await request_client(
        tmp_path,
        handler,
        app_settings=limited,
    )
    try:
        response = await client.post(
            "/cgi-bin/webhook/upload_media?key=ops&type=file",
            files={"media": ("large.txt", b"12345", "text/plain")},
        )
    finally:
        await resources.aclose()

    assert response.json()["errcode"] == 40006
