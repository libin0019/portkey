from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import (
    DynamicWebhookConfig,
    RouteConfig,
    Settings,
    load_settings,
    load_settings_from_env,
)
from .errors import RouterError
from .feishu import FeishuClient
from .store import MediaStore
from .translator import decode_image, text_payload

logger = logging.getLogger("wecom_feishu_router")
_WEBHOOK_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


def create_app(
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    media_store = MediaStore(settings.sqlite_path, settings.media_ttl_seconds)
    feishu = FeishuClient(
        settings.feishu_app,
        settings.request_timeout_seconds,
        http_client=http_client,
    )
    media_semaphore = asyncio.Semaphore(settings.max_concurrent_media_operations)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await feishu.close()
            media_store.close()

    app = FastAPI(
        title="WeCom → Feishu Router",
        version="0.3.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_bytes = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=200,
                    content={"errcode": 40008, "errmsg": "Content-Length 无效"},
                )
            if request_bytes < 0:
                return JSONResponse(
                    status_code=200,
                    content={"errcode": 40008, "errmsg": "Content-Length 无效"},
                )
            if request_bytes > settings.max_request_bytes:
                return JSONResponse(
                    status_code=200,
                    content={"errcode": 40006, "errmsg": "请求体超过大小限制"},
                )
        return await call_next(request)

    @app.exception_handler(RouterError)
    async def handle_router_error(_: Request, error: RouterError) -> JSONResponse:
        logger.warning("消息转发失败: %s", error.message)
        return JSONResponse(
            status_code=200,
            content={"errcode": error.errcode, "errmsg": error.message},
        )

    @app.exception_handler(httpx.HTTPError)
    async def handle_http_error(_: Request, error: httpx.HTTPError) -> JSONResponse:
        logger.warning("下游网络请求失败: %s", type(error).__name__)
        return JSONResponse(
            status_code=200,
            content={"errcode": 45001, "errmsg": "飞书服务网络请求失败"},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        logger.warning("企微兼容请求参数无效: %s", error.errors())
        return JSONResponse(
            status_code=200,
            content={"errcode": 40008, "errmsg": "请求参数或文件表单无效"},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/cgi-bin/webhook/send")
    async def wecom_send(
        request: Request, key: Annotated[str, Query()]
    ) -> dict[str, Any]:
        return await _send(request, key)

    @app.post("/webhook/{route_key}")
    async def short_send(request: Request, route_key: str) -> dict[str, Any]:
        return await _send(request, route_key)

    @app.post("/cgi-bin/webhook/upload_media")
    async def wecom_upload(
        key: Annotated[str, Query()],
        media: Annotated[UploadFile, File()],
        media_type: Annotated[str, Query(alias="type")] = "file",
    ) -> dict[str, Any]:
        return await _upload(key, media_type, media)

    @app.post("/webhook/{route_key}/upload_media")
    async def short_upload(
        route_key: str,
        media: Annotated[UploadFile, File()],
        media_type: Annotated[str, Query(alias="type")] = "file",
    ) -> dict[str, Any]:
        return await _upload(route_key, media_type, media)

    async def _send(request: Request, route_key: str) -> dict[str, Any]:
        route_identity, route = _resolve_route(settings, route_key)
        try:
            payload = await request.json()
        except ValueError as error:
            raise RouterError("请求体不是有效 JSON", 40008) from error
        if not isinstance(payload, dict):
            raise RouterError("请求体必须是 JSON 对象", 40008)

        msgtype = payload.get("msgtype")
        if msgtype == "image":
            async with media_semaphore:
                image = decode_image(payload, settings.max_image_bytes)
                image_key = await feishu.upload_image(image)
                await feishu.send_webhook(
                    route,
                    {"msg_type": "image", "content": {"image_key": image_key}},
                )
        elif msgtype == "file":
            file_body = payload.get("file")
            if not isinstance(file_body, dict) or not file_body.get("media_id"):
                raise RouterError("缺少 file.media_id")
            if not route.chat_id:
                raise RouterError("当前路由的文件消息需要配置 chat_id", 45003)
            media = media_store.get(route_identity, str(file_body["media_id"]))
            if media is None:
                raise RouterError(
                    "media_id 不存在或已过期；请先通过本路由上传文件", 40007
                )
            await feishu.send_file(route.chat_id, media.file_key)
        else:
            await feishu.send_webhook(route, text_payload(payload, route))
        return {"errcode": 0, "errmsg": "ok"}

    async def _upload(
        route_key: str, media_type: str, upload: UploadFile
    ) -> dict[str, Any]:
        route_identity, route = _resolve_route(settings, route_key)
        if media_type != "file":
            raise RouterError("upload_media 目前仅支持 type=file")
        if not route.chat_id:
            raise RouterError("当前路由的文件消息需要配置 chat_id", 45003)
        file_name = (
            ((upload.filename or "attachment").rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
            or "attachment"
        )
        if len(file_name.encode("utf-8")) > 250:
            raise RouterError("文件名超过 250 bytes", 40006)
        async with media_semaphore:
            file_size = await _measure_upload(upload, settings.max_file_bytes)
            if file_size == 0:
                raise RouterError("上传文件为空")
            file_key = await feishu.upload_file(file_name, upload.file)
        media_id = media_store.put(route_identity, file_key, file_name)
        return {
            "errcode": 0,
            "errmsg": "ok",
            "type": "file",
            "media_id": media_id,
            "created_at": int(time.time()),
        }

    return app


def build_app() -> FastAPI:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config_path = os.getenv("ROUTER_CONFIG")
    settings = load_settings(config_path) if config_path else load_settings_from_env()
    return create_app(settings)


def _resolve_route(settings: Settings, route_key: str) -> tuple[str, RouteConfig]:
    route = settings.routes.get(route_key)
    if route is not None:
        return route_key, route
    if settings.dynamic_webhook is None:
        raise RouterError("无效的 webhook key", 93000)
    webhook_id = _extract_webhook_id(route_key, settings.dynamic_webhook)
    return webhook_id, RouteConfig(
        webhook_url=f"{settings.dynamic_webhook.base_url}/{webhook_id}",
        webhook_secret=settings.dynamic_webhook.webhook_secret,
        mention_map=settings.dynamic_webhook.mention_map,
    )


def _extract_webhook_id(value: str, dynamic: DynamicWebhookConfig) -> str:
    candidate = value.strip()
    if "://" in candidate:
        supplied = urlparse(candidate)
        base = urlparse(dynamic.base_url)
        path_prefix = f"{base.path}/"
        if (
            supplied.scheme != base.scheme
            or supplied.netloc != base.netloc
            or not supplied.path.startswith(path_prefix)
            or supplied.params
            or supplied.query
            or supplied.fragment
        ):
            raise RouterError("无效的飞书 Webhook 地址", 93000)
        candidate = supplied.path[len(path_prefix) :]
    if not _WEBHOOK_ID_PATTERN.fullmatch(candidate):
        raise RouterError("无效的飞书 Webhook 标识", 93000)
    return candidate


async def _measure_upload(upload: UploadFile, maximum: int) -> int:
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > maximum:
            raise RouterError(f"文件超过大小限制 {maximum} bytes", 40006)
    await upload.seek(0)
    return size
