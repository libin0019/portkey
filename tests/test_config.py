from __future__ import annotations

from pathlib import Path

import pytest

from wecom_feishu_router.config import (
    ConfigError,
    load_settings,
    load_settings_from_env,
)


def test_load_settings_expands_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_WEBHOOK", "https://open.feishu.test/hook")
    config = tmp_path / "config.toml"
    config.write_text(
        """
[routes.demo]
webhook_url = "${TEST_WEBHOOK}"
""".strip(),
        encoding="utf-8",
    )

    result = load_settings(config)

    assert result.routes["demo"].webhook_url == "https://open.feishu.test/hook"


def test_missing_environment_variable_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[routes.demo]
webhook_url = "${MISSING_TEST_WEBHOOK}"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="MISSING_TEST_WEBHOOK"):
        load_settings(config)


def test_invalid_mention_map_has_actionable_error(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[routes.demo]
webhook_url = "https://open.feishu.test/hook"
mention_map = "invalid"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="mention_map 必须是 TOML 表"):
        load_settings(config)


@pytest.mark.parametrize(
    ("section", "value", "message"),
    [
        ("[limits]", "max_file_bytes = -1", "max_file_bytes 必须在"),
        ("[limits]", "max_concurrent_media_operations = 0", "必须在"),
        ("[server]", "request_timeout_seconds = 0", "必须大于 0"),
    ],
)
def test_non_positive_limits_are_rejected(
    tmp_path: Path, section: str, value: str, message: str
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
{section}
{value}
[routes.demo]
webhook_url = "https://open.feishu.test/hook"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=message):
        load_settings(config)


def test_request_limit_must_fit_media_payloads(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[limits]
max_request_bytes = 1048576
[routes.demo]
webhook_url = "https://open.feishu.test/hook"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="max_request_bytes 太小"):
        load_settings(config)


def test_load_single_route_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROUTER_WEBHOOK_KEY", "route-secret")
    monkeypatch.setenv(
        "FEISHU_WEBHOOK_URL", "https://open.feishu.test/bot/hook"
    )
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "signature-secret")
    monkeypatch.setenv("FEISHU_CHAT_ID", "oc_test")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "app-secret")
    monkeypatch.setenv(
        "ROUTER_MENTION_MAP_JSON", '{"zhangsan":"ou_zhangsan"}'
    )

    result = load_settings_from_env()

    route = result.routes["route-secret"]
    assert route.webhook_url == "https://open.feishu.test/bot/hook"
    assert route.webhook_secret == "signature-secret"
    assert route.chat_id == "oc_test"
    assert route.mention_map == {"zhangsan": "ou_zhangsan"}
    assert result.feishu_app is not None
    assert result.feishu_app.app_id == "cli_test"
    assert result.sqlite_path == Path("/app/data/router.db")


def test_load_multiple_routes_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ROUTER_ROUTES_JSON",
        """
        {
          "ops": {"webhook_url": "https://open.feishu.test/ops"},
          "finance": {
            "webhook_url": "https://open.feishu.test/finance",
            "chat_id": "oc_finance"
          }
        }
        """,
    )

    result = load_settings_from_env()

    assert set(result.routes) == {"ops", "finance"}
    assert result.routes["finance"].chat_id == "oc_finance"
    assert result.feishu_app is None


def test_environment_rejects_conflicting_route_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROUTER_WEBHOOK_KEY", "route-secret")
    monkeypatch.setenv(
        "ROUTER_ROUTES_JSON",
        '{"ops":{"webhook_url":"https://open.feishu.test/ops"}}',
    )

    with pytest.raises(ConfigError, match="不能同时配置"):
        load_settings_from_env()


def test_environment_rejects_partial_app_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROUTER_WEBHOOK_KEY", "route-secret")
    monkeypatch.setenv(
        "FEISHU_WEBHOOK_URL", "https://open.feishu.test/bot/hook"
    )
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")

    with pytest.raises(ConfigError, match="必须同时配置"):
        load_settings_from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ROUTER_ROUTES_JSON", "not-json", "有效的 JSON 对象"),
        ("ROUTER_ROUTES_JSON", "[]", "必须是 JSON 对象"),
        ("MAX_FILE_BYTES", "invalid", "必须是整数"),
    ],
)
def test_environment_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    if name != "ROUTER_ROUTES_JSON":
        monkeypatch.setenv("ROUTER_WEBHOOK_KEY", "route-secret")
        monkeypatch.setenv(
            "FEISHU_WEBHOOK_URL", "https://open.feishu.test/bot/hook"
        )
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=message):
        load_settings_from_env()
