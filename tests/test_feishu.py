from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest

from wecom_feishu_router.config import FeishuAppConfig, RouteConfig
from wecom_feishu_router.errors import FeishuAPIError
from wecom_feishu_router.feishu import FeishuClient


@pytest.mark.asyncio
async def test_webhook_response_requires_status_code() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FeishuClient(None, 1, http)
        with pytest.raises(FeishuAPIError, match="缺少状态码"):
            await client.send_webhook(
                RouteConfig("https://open.feishu.test/hook"),
                {"msg_type": "text", "content": {"text": "test"}},
            )


@pytest.mark.asyncio
async def test_application_response_requires_code() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "token", "expire": 7200},
            )
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FeishuClient(
            FeishuAppConfig("app", "secret", "https://open.feishu.test/open-apis"),
            1,
            http,
        )
        with pytest.raises(FeishuAPIError, match="响应缺少 code"):
            await client.send_file("oc_test", "file_test")


@pytest.mark.asyncio
async def test_invalid_token_is_refreshed_and_request_retried() -> None:
    token_calls = 0
    message_calls = 0
    authorizations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, message_calls
        if request.url.path.endswith("/internal"):
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": f"token-{token_calls}",
                    "expire": 7200,
                },
            )
        message_calls += 1
        authorizations.append(request.headers["Authorization"])
        if message_calls == 1:
            return httpx.Response(
                400, json={"code": 99991663, "msg": "invalid tenant token"}
            )
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FeishuClient(
            FeishuAppConfig("app", "secret", "https://open.feishu.test/open-apis"),
            1,
            http,
        )
        await client.send_file("oc_test", "file_test")

    assert token_calls == 2
    assert message_calls == 2
    assert authorizations == ["Bearer token-1", "Bearer token-2"]


@pytest.mark.asyncio
async def test_webhook_signature_matches_feishu_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    monkeypatch.setattr("wecom_feishu_router.feishu.time.time", lambda: 1_700_000_000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FeishuClient(None, 1, http)
        await client.send_webhook(
            RouteConfig(
                "https://open.feishu.test/hook",
                webhook_secret="sign-secret",
            ),
            {"msg_type": "text", "content": {"text": "test"}},
        )

    string_to_sign = b"1700000000\nsign-secret"
    expected = base64.b64encode(
        hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    ).decode()
    assert captured["timestamp"] == "1700000000"
    assert captured["sign"] == expected
