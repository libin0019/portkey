#!/bin/sh
set -eu

package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$package_dir"

command -v docker >/dev/null 2>&1 || {
  echo "未找到 docker 命令" >&2
  exit 1
}
docker info >/dev/null
docker compose version >/dev/null

[ -f .env ] || {
  echo "缺少 .env，请从 .env.example 复制后填写" >&2
  exit 1
}

if grep -Eq '^ROUTER_IMAGE=registry\.example\.com/' .env; then
  echo "请先在 .env 中填写已发布的 ROUTER_IMAGE" >&2
  exit 1
fi
if grep -Eiq '^DYNAMIC_WEBHOOK_ENABLED=(true|1|yes|on)$' .env; then
  :
elif grep -Eq '^ROUTER_ROUTES_JSON=.+$' .env; then
  :
else
  if ! grep -Eq '^ROUTER_WEBHOOK_KEY=.+$' .env ||
    grep -Eq '^ROUTER_WEBHOOK_KEY=(replace_|$)' .env; then
    echo "请在 .env 中启用动态 Webhook 或填写 ROUTER_WEBHOOK_KEY" >&2
    exit 1
  fi
  if ! grep -Eq '^FEISHU_WEBHOOK_URL=https?://.+$' .env ||
    grep -Eq '^FEISHU_WEBHOOK_URL=.*(/xxxxxxxx|=$)' .env; then
    echo "请在 .env 中填写真实的 FEISHU_WEBHOOK_URL" >&2
    exit 1
  fi
fi

chmod 600 .env
docker compose config --quiet
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
