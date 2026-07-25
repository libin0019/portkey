#!/bin/sh
set -eu

version="${1:-0.2.0}"
target_platform="${2:-linux/amd64}"
image_repository="${IMAGE_REPOSITORY:-wecom-feishu-router}"
image="${image_repository}:${version}"

case "$version" in
  *[!A-Za-z0-9._-]* | "")
    echo "版本号只能包含字母、数字、点、下划线和连字符" >&2
    exit 2
    ;;
esac

case "$target_platform" in
  linux/amd64)
    platform_name="linux-amd64"
    ;;
  linux/arm64 | linux/arm64/v8)
    platform_name="linux-arm64"
    ;;
  *)
    echo "支持的平台: linux/amd64、linux/arm64" >&2
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
dist_dir="$project_dir/dist"
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/wecom-feishu-release.XXXXXX")
release_name="wecom-feishu-router-${version}-${platform_name}"
release_dir="$work_dir/$release_name"
image_archive="$release_dir/image/${image_repository##*/}-${version}-${platform_name}.tar.gz"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$release_dir/image" "$dist_dir"

echo "构建镜像: $image ($target_platform)"
docker buildx build \
  --platform "$target_platform" \
  --build-arg "APP_VERSION=$version" \
  --tag "$image" \
  --load \
  "$project_dir"

echo "导出镜像: $image_archive"
docker image save "$image" | gzip -9 > "$image_archive"

cp "$project_dir/docker-compose.yml" "$release_dir/"
cp "$project_dir/docker-compose.offline.yml" "$release_dir/"
cp "$project_dir/.env.example" "$release_dir/"
cp "$project_dir/docs/DOCKER_COMPOSE_DEPLOYMENT.md" "$release_dir/"
cp "$project_dir/deploy/nginx/wecom-feishu-router.conf" "$release_dir/nginx.conf.example"
cp "$project_dir/scripts/load-compose-package.sh" "$release_dir/"
chmod +x "$release_dir/load-compose-package.sh"

sed \
  "s|^ROUTER_IMAGE=.*|ROUTER_IMAGE=${image}|" \
  "$project_dir/.env.example" > "$release_dir/.env.example"

cat > "$release_dir/RELEASE_INFO" <<EOF
NAME=wecom-feishu-router
VERSION=$version
IMAGE=$image
PLATFORM=$target_platform
EOF

(
  cd "$release_dir"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "image/$(basename "$image_archive")" > SHA256SUMS
  else
    shasum -a 256 "image/$(basename "$image_archive")" > SHA256SUMS
  fi
)

package="$dist_dir/$release_name.tar.gz"
tar -C "$work_dir" -czf "$package" "$release_name"

(
  cd "$dist_dir"
  package_name=$(basename "$package")
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$package_name" > "$package_name.sha256"
  else
    shasum -a 256 "$package_name" > "$package_name.sha256"
  fi
)

echo "部署包已生成:"
echo "  $package"
echo "  $package.sha256"
