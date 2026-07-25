#!/bin/sh
set -eu

image="${1:-}"
platforms="${2:-linux/amd64,linux/arm64}"

if [ -z "$image" ]; then
  echo "用法: $0 <镜像完整地址:标签> [平台列表]" >&2
  echo "示例: $0 ghcr.io/example/wecom-feishu-router:0.2.0" >&2
  exit 2
fi

case "$image" in
  *[[:space:]]* | *:latest | latest)
    echo "镜像地址不能包含空白，也不能使用 latest 标签" >&2
    exit 2
    ;;
  *:*)
    ;;
  *)
    echo "镜像地址必须包含明确的版本标签" >&2
    exit 2
    ;;
esac

case "$platforms" in
  *[!A-Za-z0-9,/_-]* | "")
    echo "平台列表格式无效" >&2
    exit 2
    ;;
esac

command -v docker >/dev/null 2>&1 || {
  echo "未找到 docker 命令" >&2
  exit 1
}
docker info >/dev/null
docker buildx version >/dev/null

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

echo "构建并推送镜像: $image"
echo "目标平台: $platforms"
docker buildx build \
  --platform "$platforms" \
  --build-arg "APP_VERSION=0.2.0" \
  --tag "$image" \
  --push \
  "$project_dir"

echo "镜像已推送: $image"
