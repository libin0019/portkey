#!/bin/sh
set -eu

version="${1:-0.2.0}"

case "$version" in
  *[!A-Za-z0-9._-]* | "")
    echo "版本号只能包含字母、数字、点、下划线和连字符" >&2
    exit 2
    ;;
esac

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dist_dir="$project_dir/dist"
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/wecom-feishu-source.XXXXXX")
release_name="wecom-feishu-router-${version}-compose-source"
release_dir="$work_dir/$release_name"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

mkdir -p \
  "$release_dir/.github/workflows" \
  "$release_dir/src" \
  "$release_dir/docs" \
  "$release_dir/deploy/nginx" \
  "$release_dir/scripts" \
  "$dist_dir"

cp "$project_dir/Dockerfile" "$release_dir/"
cp "$project_dir/docker-compose.yml" "$release_dir/"
cp "$project_dir/docker-compose.build.yml" "$release_dir/"
cp "$project_dir/pyproject.toml" "$release_dir/"
cp "$project_dir/requirements.lock" "$release_dir/"
cp "$project_dir/README.md" "$release_dir/"
cp "$project_dir/.env.example" "$release_dir/"
cp "$project_dir/.dockerignore" "$release_dir/"
cp "$project_dir/.github/workflows/publish-container.yml" \
  "$release_dir/.github/workflows/"
cp -R "$project_dir/src/wecom_feishu_router" "$release_dir/src/"
cp "$project_dir/docs/DOCKER_COMPOSE_DEPLOYMENT.md" "$release_dir/docs/"
cp "$project_dir/docs/REGISTRY_COMPOSE_DEPLOYMENT.md" "$release_dir/docs/"
cp "$project_dir/deploy/nginx/wecom-feishu-router.conf" "$release_dir/deploy/nginx/"
cp "$project_dir/scripts/package-compose.sh" "$release_dir/scripts/"
cp "$project_dir/scripts/load-compose-package.sh" "$release_dir/scripts/"
cp "$project_dir/scripts/publish-image.sh" "$release_dir/scripts/"
cp "$project_dir/scripts/package-registry-deploy.sh" "$release_dir/scripts/"
cp "$project_dir/scripts/deploy-registry-package.sh" "$release_dir/scripts/"

find "$release_dir/src" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$release_dir/src" -type f -name '*.pyc' -delete

cat > "$release_dir/RELEASE_INFO" <<EOF
NAME=wecom-feishu-router
VERSION=$version
TYPE=compose-source
START_COMMAND=docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
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

echo "Compose 源码部署包已生成:"
echo "  $package"
echo "  $package.sha256"
