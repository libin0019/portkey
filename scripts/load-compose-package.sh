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

set -- image/*.tar.gz
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "image 目录中必须且只能有一个 .tar.gz 镜像包" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum -c SHA256SUMS
else
  shasum -a 256 -c SHA256SUMS
fi

docker image load --input "$1"

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "已创建 .env，请填写真实飞书参数。"
fi

echo
echo "镜像导入完成。完成配置后执行："
echo "  docker compose config --quiet"
echo "  docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d --no-build"
