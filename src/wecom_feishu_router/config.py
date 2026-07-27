from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class FeishuAppConfig:
    app_id: str
    app_secret: str
    api_base: str = "https://open.feishu.cn/open-apis"


@dataclass(frozen=True)
class RouteConfig:
    webhook_url: str
    chat_id: str | None = None
    webhook_secret: str | None = None
    mention_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DynamicWebhookConfig:
    base_url: str = "https://open.feishu.cn/open-apis/bot/v2/hook"
    webhook_secret: str | None = None
    mention_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    routes: dict[str, RouteConfig]
    dynamic_webhook: DynamicWebhookConfig | None = None
    feishu_app: FeishuAppConfig | None = None
    sqlite_path: Path = Path("./data/router.db")
    media_ttl_seconds: int = 259_200
    max_image_bytes: int = 10 * 1024 * 1024
    max_file_bytes: int = 20 * 1024 * 1024
    max_request_bytes: int = 24 * 1024 * 1024
    max_concurrent_media_operations: int = 4
    request_timeout_seconds: float = 15.0


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"环境变量 {name} 未设置")
            return os.environ[name]

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在: {config_path}")

    with config_path.open("rb") as config_file:
        data = _expand_env(tomllib.load(config_file))
    return _settings_from_data(data)


def load_settings_from_env() -> Settings:
    routes_json = os.getenv("ROUTER_ROUTES_JSON")
    route_key = os.getenv("ROUTER_WEBHOOK_KEY")
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
    dynamic_enabled = _env_bool("DYNAMIC_WEBHOOK_ENABLED", False)
    if routes_json and (route_key or webhook_url):
        raise ConfigError("ROUTER_ROUTES_JSON 与单路由环境变量不能同时配置")

    if routes_json:
        routes = _json_object(routes_json, "ROUTER_ROUTES_JSON")
    elif route_key or webhook_url:
        route_key = _required_env("ROUTER_WEBHOOK_KEY")
        route: dict[str, Any] = {"webhook_url": _required_env("FEISHU_WEBHOOK_URL")}
        optional_route_values = {
            "webhook_secret": os.getenv("FEISHU_WEBHOOK_SECRET"),
            "chat_id": os.getenv("FEISHU_CHAT_ID"),
        }
        route.update(
            {
                name: value
                for name, value in optional_route_values.items()
                if value and value.strip()
            }
        )
        mention_map_json = os.getenv("ROUTER_MENTION_MAP_JSON")
        if mention_map_json:
            route["mention_map"] = _json_object(
                mention_map_json, "ROUTER_MENTION_MAP_JSON"
            )
        routes = {route_key: route}
    elif dynamic_enabled:
        routes = {}
    else:
        raise ConfigError(
            "未配置静态路由；如需从请求 key 拼接飞书 Webhook，"
            "请设置 DYNAMIC_WEBHOOK_ENABLED=true"
        )

    data: dict[str, Any] = {
        "routes": routes,
        "server": {
            "request_timeout_seconds": _env_float("REQUEST_TIMEOUT_SECONDS", 15.0)
        },
        "storage": {
            "sqlite_path": os.getenv("SQLITE_PATH", "/app/data/router.db"),
            "media_ttl_seconds": _env_int("MEDIA_TTL_SECONDS", 259_200),
        },
        "limits": {
            "max_image_bytes": _env_int("MAX_IMAGE_BYTES", 10 * 1024 * 1024),
            "max_file_bytes": _env_int("MAX_FILE_BYTES", 20 * 1024 * 1024),
            "max_request_bytes": _env_int("MAX_REQUEST_BYTES", 24 * 1024 * 1024),
            "max_concurrent_media_operations": _env_int(
                "MAX_CONCURRENT_MEDIA_OPERATIONS", 4
            ),
        },
    }
    if dynamic_enabled:
        dynamic_data: dict[str, Any] = {
            "enabled": True,
            "base_url": os.getenv(
                "FEISHU_WEBHOOK_BASE_URL",
                "https://open.feishu.cn/open-apis/bot/v2/hook",
            ),
        }
        dynamic_secret = os.getenv("DYNAMIC_WEBHOOK_SECRET")
        if dynamic_secret and dynamic_secret.strip():
            dynamic_data["webhook_secret"] = dynamic_secret
        dynamic_mention_map = os.getenv("DYNAMIC_MENTION_MAP_JSON")
        if dynamic_mention_map:
            dynamic_data["mention_map"] = _json_object(
                dynamic_mention_map, "DYNAMIC_MENTION_MAP_JSON"
            )
        data["dynamic_webhook"] = dynamic_data

    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if bool(app_id and app_id.strip()) != bool(app_secret and app_secret.strip()):
        raise ConfigError("FEISHU_APP_ID 与 FEISHU_APP_SECRET 必须同时配置")
    if app_id and app_secret:
        data["feishu_app"] = {
            "app_id": app_id,
            "app_secret": app_secret,
            "api_base": os.getenv(
                "FEISHU_API_BASE", "https://open.feishu.cn/open-apis"
            ),
        }
    return _settings_from_data(data)


def _settings_from_data(data: Any) -> Settings:
    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点必须是 TOML 表")

    dynamic_data = _table(data, "dynamic_webhook")
    dynamic_webhook = None
    if _boolean(dynamic_data, "enabled", False):
        base_url = (
            _optional_string(dynamic_data.get("base_url"), "dynamic_webhook.base_url")
            or "https://open.feishu.cn/open-apis/bot/v2/hook"
        ).rstrip("/")
        _validate_dynamic_webhook_base(base_url)
        dynamic_webhook = DynamicWebhookConfig(
            base_url=base_url,
            webhook_secret=_optional_string(
                dynamic_data.get("webhook_secret"),
                "dynamic_webhook.webhook_secret",
            ),
            mention_map=_mention_map(dynamic_data, "dynamic_webhook"),
        )

    route_data = _table(data, "routes")
    if not route_data and dynamic_webhook is None:
        raise ConfigError("至少需要配置一个静态路由或启用 dynamic_webhook")

    routes: dict[str, RouteConfig] = {}
    for route_key, item in route_data.items():
        if not isinstance(item, dict):
            raise ConfigError(f"路由 {route_key!r} 必须是 TOML 表")
        webhook_url = _required_string(item, "webhook_url", f"routes.{route_key}")
        _validate_http_url(webhook_url, f"routes.{route_key}.webhook_url")
        if not route_key.strip():
            raise ConfigError(f"路由 {route_key!r} 缺少 webhook_url")
        routes[route_key] = RouteConfig(
            webhook_url=webhook_url,
            chat_id=_optional_string(
                item.get("chat_id"), f"routes.{route_key}.chat_id"
            ),
            webhook_secret=_optional_string(
                item.get("webhook_secret"), f"routes.{route_key}.webhook_secret"
            ),
            mention_map=_mention_map(item, f"routes.{route_key}"),
        )

    app_data = data.get("feishu_app")
    feishu_app = None
    if app_data is not None:
        if not isinstance(app_data, dict):
            raise ConfigError("[feishu_app] 必须是 TOML 表")
        app_id = _required_string(app_data, "app_id", "feishu_app")
        app_secret = _required_string(app_data, "app_secret", "feishu_app")
        api_base = (
            _optional_string(app_data.get("api_base"), "feishu_app.api_base")
            or "https://open.feishu.cn/open-apis"
        )
        _validate_http_url(api_base, "feishu_app.api_base")
        feishu_app = FeishuAppConfig(
            app_id=app_id,
            app_secret=app_secret,
            api_base=api_base.rstrip("/"),
        )

    storage = _table(data, "storage")
    limits = _table(data, "limits")
    server = _table(data, "server")
    sqlite_path = (
        _optional_string(storage.get("sqlite_path"), "storage.sqlite_path")
        or "./data/router.db"
    )
    max_image_bytes = _positive_int(
        limits, "max_image_bytes", 10 * 1024 * 1024, maximum=10 * 1024 * 1024
    )
    max_file_bytes = _positive_int(
        limits, "max_file_bytes", 20 * 1024 * 1024, maximum=30 * 1024 * 1024
    )
    max_request_bytes = _positive_int(
        limits, "max_request_bytes", 24 * 1024 * 1024, maximum=64 * 1024 * 1024
    )
    minimum_request_bytes = max(
        max_file_bytes + 1024 * 1024,
        ((max_image_bytes + 2) // 3) * 4 + 1024 * 1024,
    )
    if max_request_bytes < minimum_request_bytes:
        raise ConfigError(
            "max_request_bytes 太小，至少应为文件上限或图片 Base64 上限再加 1 MiB"
        )
    return Settings(
        routes=routes,
        dynamic_webhook=dynamic_webhook,
        feishu_app=feishu_app,
        sqlite_path=Path(sqlite_path),
        media_ttl_seconds=_positive_int(
            storage, "media_ttl_seconds", 259_200, maximum=31_536_000
        ),
        max_image_bytes=max_image_bytes,
        max_file_bytes=max_file_bytes,
        max_request_bytes=max_request_bytes,
        max_concurrent_media_operations=_positive_int(
            limits, "max_concurrent_media_operations", 4, maximum=64
        ),
        request_timeout_seconds=_positive_float(
            server, "request_timeout_seconds", 15.0, maximum=300.0
        ),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ConfigError(f"环境变量 {name} 未设置或为空")
    return value.strip()


def _json_object(value: str, name: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError as error:
        raise ConfigError(f"{name} 必须是有效的 JSON 对象") from error
    if not isinstance(result, dict):
        raise ConfigError(f"{name} 必须是 JSON 对象")
    return result


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ConfigError(f"环境变量 {name} 必须是整数") from error


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ConfigError(f"环境变量 {name} 必须是数字") from error


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"环境变量 {name} 必须是 true 或 false")


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] 必须是 TOML 表")
    return value


def _required_string(data: dict[str, Any], key: str, section: str) -> str:
    value = _optional_string(data.get(key), f"{section}.{key}")
    if value is None:
        raise ConfigError(f"{section}.{key} 必须是非空字符串")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{name} 必须是字符串")
    result = value.strip()
    return result or None


def _mention_map(data: dict[str, Any], section: str) -> dict[str, str]:
    mention_data = data.get("mention_map", {})
    if not isinstance(mention_data, dict):
        raise ConfigError(f"{section}.mention_map 必须是 TOML 表")
    mention_map: dict[str, str] = {}
    for source, target in mention_data.items():
        if not isinstance(target, str) or not target.strip():
            raise ConfigError(f"{section}.mention_map.{source} 必须是非空字符串")
        mention_map[str(source)] = target.strip()
    return mention_map


def _boolean(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} 必须是布尔值")
    return value


def _positive_int(
    data: dict[str, Any],
    key: str,
    default: int,
    *,
    maximum: int,
) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} 必须是整数")
    if value <= 0 or value > maximum:
        raise ConfigError(f"{key} 必须在 1 到 {maximum} 之间")
    return value


def _positive_float(
    data: dict[str, Any],
    key: str,
    default: float,
    *,
    maximum: float,
) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} 必须是数字")
    result = float(value)
    if result <= 0 or result > maximum:
        raise ConfigError(f"{key} 必须大于 0 且不超过 {maximum}")
    return result


def _validate_http_url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} 必须是有效的 HTTP(S) URL")


def _validate_dynamic_webhook_base(value: str) -> None:
    parsed = urlparse(value)
    allowed_hosts = {"open.feishu.cn", "open.larksuite.com"}
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.netloc != parsed.hostname
        or parsed.path != "/open-apis/bot/v2/hook"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError(
            "dynamic_webhook.base_url 必须是飞书或 Lark 官方 V2 Webhook 基地址"
        )
