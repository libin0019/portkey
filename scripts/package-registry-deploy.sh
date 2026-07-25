#!/bin/sh
set -eu

image="${1:-}"
version="${VERSION:-0.2.0}"

if [ -z "$image" ]; then
  echo "用法: $0 <已发布的镜像完整地址:标签>" >&2
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

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dist_dir="$project_dir/dist"
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/wecom-feishu-pull.XXXXXX")
release_name="wecom-feishu-router-${version}-compose-pull"
release_dir="$work_dir/$release_name"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$release_dir" "$dist_dir"

cp "$project_dir/docker-compose.yml" "$release_dir/"
cp "$project_dir/docs/REGISTRY_COMPOSE_DEPLOYMENT.md" "$release_dir/README.md"
cp "$project_dir/deploy/nginx/wecom-feishu-router.conf" \
  "$release_dir/nginx.conf.example"
cp "$project_dir/scripts/deploy-registry-package.sh" "$release_dir/deploy.sh"
chmod +x "$release_dir/deploy.sh"

sed \
  "s|^ROUTER_IMAGE=.*|ROUTER_IMAGE=$image|" \
  "$project_dir/.env.example" > "$release_dir/.env"
cp "$release_dir/.env" "$release_dir/.env.example"
chmod 600 "$release_dir/.env" "$release_dir/.env.example"

cat > "$release_dir/RELEASE_INFO" <<EOF
NAME=wecom-feishu-router
VERSION=$version
IMAGE=$image
TYPE=compose-registry-pull
START_COMMAND=./deploy.sh
EOF

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

echo "镜像拉取式 Compose 部署包已生成:"
echo "  $package"
echo "  $package.sha256"
