from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from .config import FeishuAppConfig, RouteConfig
from .errors import FeishuAPIError

_TOKEN_ERROR_CODES = {99991661, 99991663, 99991664}


class FeishuClient:
    def __init__(
        self,
        app_config: FeishuAppConfig | None,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._app_config = app_config
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_http = http_client is None
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def send_webhook(self, route: RouteConfig, payload: dict[str, Any]) -> None:
        body = dict(payload)
        if route.webhook_secret:
            timestamp = str(int(time.time()))
            body["timestamp"] = timestamp
            body["sign"] = _webhook_signature(timestamp, route.webhook_secret)
        response = await self._http.post(route.webhook_url, json=body)
        data = _response_json(response, "飞书 Webhook")
        if "code" in data:
            code = data["code"]
        elif "StatusCode" in data:
            code = data["StatusCode"]
        else:
            raise FeishuAPIError("飞书 Webhook 响应缺少状态码", 45002)
        if not _is_success_code(code):
            message = data.get("msg", data.get("StatusMessage", "未知错误"))
            raise FeishuAPIError(f"飞书 Webhook 失败: {code} {message}", 45001)

    async def upload_image(self, content: bytes) -> str:
        data = await self._authenticated_request(
            "飞书图片上传",
            "POST",
            "/im/v1/images",
            data={"image_type": "message"},
            files={"image": ("image.png", content, "application/octet-stream")},
        )
        try:
            return str(data["data"]["image_key"])
        except (KeyError, TypeError) as error:
            raise FeishuAPIError("飞书图片上传响应缺少 image_key", 45002) from error

    async def upload_file(self, file_name: str, content: bytes | BinaryIO) -> str:
        data = await self._authenticated_request(
            "飞书文件上传",
            "POST",
            "/im/v1/files",
            data={
                "file_type": _feishu_file_type(file_name),
                "file_name": file_name,
            },
            files={"file": (file_name, content, "application/octet-stream")},
        )
        try:
            return str(data["data"]["file_key"])
        except (KeyError, TypeError) as error:
            raise FeishuAPIError("飞书文件上传响应缺少 file_key", 45002) from error

    async def send_file(self, chat_id: str, file_key: str) -> None:
        await self._authenticated_request(
            "飞书文件消息发送",
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": chat_id,
                "msg_type": "file",
                "content": json.dumps(
                    {"file_key": file_key}, ensure_ascii=False, separators=(",", ":")
                ),
            },
        )

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    @property
    def _api_base(self) -> str:
        if self._app_config is None:
            raise FeishuAPIError("图片/文件消息需要配置 [feishu_app]", 45003)
        return self._app_config.api_base

    async def _tenant_token(self) -> str:
        if self._app_config is None:
            raise FeishuAPIError("图片/文件消息需要配置 [feishu_app]", 45003)
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            response = await self._http.post(
                f"{self._app_config.api_base}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self._app_config.app_id,
                    "app_secret": self._app_config.app_secret,
                },
            )
            data = _response_json(response, "飞书访问凭证获取")
            _ensure_success(data, "飞书访问凭证获取")
            token = data.get("tenant_access_token")
            if not token:
                raise FeishuAPIError("飞书访问凭证响应缺少 token", 45002)
            try:
                expire_seconds = int(data.get("expire", 7200))
            except (TypeError, ValueError) as error:
                raise FeishuAPIError("飞书访问凭证响应的 expire 无效", 45002) from error
            if expire_seconds <= 0:
                raise FeishuAPIError("飞书访问凭证已过期", 45002)
            expire = (
                expire_seconds - 300
                if expire_seconds > 600
                else max(int(expire_seconds * 0.8), 1)
            )
            self._token = str(token)
            self._token_expires_at = time.monotonic() + expire
            return self._token

    async def _authenticated_request(
        self,
        operation: str,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        for attempt in range(2):
            token = await self._tenant_token()
            headers = {
                **kwargs.get("headers", {}),
                "Authorization": f"Bearer {token}",
            }
            request_kwargs = {**kwargs, "headers": headers}
            _rewind_files(request_kwargs.get("files"))
            response = await self._http.request(
                method,
                f"{self._api_base}{path}",
                **request_kwargs,
            )

            if response.status_code == 401 and attempt == 0:
                await self._invalidate_token(token)
                continue

            candidate = _try_json_dict(response)
            if candidate and _is_token_error(candidate.get("code")) and attempt == 0:
                await self._invalidate_token(token)
                continue

            data = _response_json(response, operation)
            _ensure_success(data, operation)
            return data

        raise FeishuAPIError(f"{operation}鉴权失败", 45001)

    async def _invalidate_token(self, failed_token: str) -> None:
        async with self._token_lock:
            if self._token == failed_token:
                self._token = None
                self._token_expires_at = 0.0


def _response_json(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise FeishuAPIError(
            f"{operation} HTTP {response.status_code}", 45001
        ) from error
    try:
        data = response.json()
    except ValueError as error:
        raise FeishuAPIError(f"{operation} 返回非 JSON 响应", 45001) from error
    if not isinstance(data, dict):
        raise FeishuAPIError(f"{operation} 返回格式无效", 45001)
    return data


def _try_json_dict(response: httpx.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _ensure_success(data: dict[str, Any], operation: str) -> None:
    if "code" not in data:
        raise FeishuAPIError(f"{operation}响应缺少 code", 45002)
    code = data["code"]
    if not _is_success_code(code):
        raise FeishuAPIError(
            f"{operation}失败: {code} {data.get('msg', '未知错误')}", 45001
        )


def _webhook_signature(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _feishu_file_type(file_name: str) -> str:
    extension = Path(file_name).suffix.lower()
    return {
        ".opus": "opus",
        ".mp4": "mp4",
        ".pdf": "pdf",
        ".doc": "doc",
        ".docx": "doc",
        ".xls": "xls",
        ".xlsx": "xls",
        ".ppt": "ppt",
        ".pptx": "ppt",
    }.get(extension, "stream")


def _is_success_code(code: Any) -> bool:
    return code == 0 or code == "0"


def _is_token_error(code: Any) -> bool:
    try:
        return int(code) in _TOKEN_ERROR_CODES
    except (TypeError, ValueError):
        return False


def _rewind_files(files: Any) -> None:
    if not files:
        return
    values = files.values() if isinstance(files, dict) else (item[1] for item in files)
    for value in values:
        file_value = value[1] if isinstance(value, tuple) and len(value) >= 2 else value
        seek = getattr(file_value, "seek", None)
        if callable(seek):
            seek(0)
