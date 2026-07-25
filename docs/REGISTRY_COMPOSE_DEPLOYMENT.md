# 镜像仓库 Docker Compose 部署手册

该部署模式满足以下目标：

- 服务器不保存项目源码。
- `docker-compose.yml` 只包含远程 `image:`，不执行本地构建。
- 所有应用参数只配置在 `.env`，不需要 `config.toml`。
- 支持 Docker Hub、GitHub Container Registry 和 AWS ECR。

## 1. 发布镜像

必须先准备一个镜像仓库。镜像需要明确版本号，不要使用 `latest`。

### 项目默认 GHCR 镜像

项目包含 `.github/workflows/publish-container.yml`。代码进入 GitHub 仓库的 `main`
分支后，GitHub Actions 会使用仓库自带的 `GITHUB_TOKEN` 自动创建并发布：

```text
ghcr.io/libin0019/portkey:0.2.0
```

首次发布后，在 GitHub 账号的 Packages 页面进入 `portkey`，将 Package visibility
设为 Public，EC2 即可匿名拉取。保持私有时，EC2 需要使用具有 `read:packages`
权限的 GitHub PAT 执行 `docker login ghcr.io`。

### Docker Hub 示例

```bash
docker login
chmod +x scripts/publish-image.sh
./scripts/publish-image.sh \
  docker.io/<DockerHub账号>/wecom-feishu-router:0.2.0
```

### AWS ECR 示例

```bash
AWS_REGION=ap-southeast-1
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws ecr describe-repositories \
  --region "$AWS_REGION" \
  --repository-names wecom-feishu-router >/dev/null 2>&1 ||
aws ecr create-repository \
  --region "$AWS_REGION" \
  --repository-name wecom-feishu-router

aws ecr get-login-password --region "$AWS_REGION" |
docker login \
  --username AWS \
  --password-stdin \
  "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

IMAGE="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/wecom-feishu-router:0.2.0"
./scripts/publish-image.sh "$IMAGE"
```

`publish-image.sh` 默认同时发布 `linux/amd64` 和 `linux/arm64`。只发布 EC2 x86_64
镜像时：

```bash
./scripts/publish-image.sh "$IMAGE" linux/amd64
```

## 2. 生成服务器部署包

镜像发布成功后执行：

```bash
chmod +x scripts/package-registry-deploy.sh
./scripts/package-registry-deploy.sh "$IMAGE"
```

输出：

```text
dist/wecom-feishu-router-0.2.0-compose-pull.tar.gz
dist/wecom-feishu-router-0.2.0-compose-pull.tar.gz.sha256
```

部署包只包含：

- `docker-compose.yml`
- 已写入镜像地址的 `.env` 和 `.env.example`
- `deploy.sh`
- 本手册和 Nginx 示例

部署包不包含项目源码和真实飞书凭证。

## 3. 上传服务器

```bash
scp dist/wecom-feishu-router-0.2.0-compose-pull.tar.gz* \
  ubuntu@<EC2-IP>:/tmp/
```

服务器执行：

```bash
cd /tmp
sha256sum -c wecom-feishu-router-0.2.0-compose-pull.tar.gz.sha256

sudo mkdir -p /opt/wecom-feishu-router
sudo tar -xzf wecom-feishu-router-0.2.0-compose-pull.tar.gz \
  -C /opt/wecom-feishu-router \
  --strip-components=1
sudo chown -R "$(id -un):$(id -gn)" /opt/wecom-feishu-router
cd /opt/wecom-feishu-router
```

私有仓库需要先登录。AWS ECR 示例：

```bash
aws ecr get-login-password --region ap-southeast-1 |
docker login \
  --username AWS \
  --password-stdin \
  <AWS账号ID>.dkr.ecr.ap-southeast-1.amazonaws.com
```

## 4. 配置 `.env`

生成随机 Webhook 路由密钥：

```bash
openssl rand -hex 32
```

编辑：

```bash
vi .env
chmod 600 .env
```

单群完整示例：

```dotenv
COMPOSE_PROJECT_NAME=wecom-feishu-router
ROUTER_IMAGE=<镜像仓库>/wecom-feishu-router:0.2.0
ROUTER_BIND_IP=127.0.0.1
ROUTER_PORT=8000
LOG_LEVEL=INFO

ROUTER_WEBHOOK_KEY=<openssl生成的随机值>
FEISHU_WEBHOOK_URL='https://open.feishu.cn/open-apis/bot/v2/hook/xxx'
FEISHU_WEBHOOK_SECRET='群机器人签名密钥'
FEISHU_CHAT_ID=oc_xxx

FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET='应用密钥'

SQLITE_PATH=/app/data/router.db
MEDIA_TTL_SECONDS=259200
MAX_IMAGE_BYTES=10485760
MAX_FILE_BYTES=20971520
MAX_REQUEST_BYTES=25165824
MAX_CONCURRENT_MEDIA_OPERATIONS=4
REQUEST_TIMEOUT_SECONDS=15
```

没有启用群机器人签名时保持：

```dotenv
FEISHU_WEBHOOK_SECRET=
```

仅转发文本时，以下变量可以留空：

```dotenv
FEISHU_CHAT_ID=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

多群时删除或注释以下单群变量：

```dotenv
ROUTER_WEBHOOK_KEY=
FEISHU_WEBHOOK_URL=
FEISHU_WEBHOOK_SECRET=
FEISHU_CHAT_ID=
```

然后增加一行 `ROUTER_ROUTES_JSON`：

```dotenv
ROUTER_ROUTES_JSON='{"key1":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/xxx","webhook_secret":"secret1","chat_id":"oc_xxx"},"key2":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/yyy","chat_id":"oc_yyy"}}'
```

成员映射可放在路由的 `mention_map` 中：

```json
{"key1":{"webhook_url":"https://example/hook","mention_map":{"zhangsan":"ou_xxx"}}}
```

## 5. 拉取并启动

部署包提供一键脚本，会依次校验配置、拉取镜像并启动：

```bash
./deploy.sh
```

等效手工命令：

```bash
docker compose config --quiet
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
```

检查：

```bash
curl -fsS http://127.0.0.1:8000/healthz
docker compose logs --tail=200 router
```

预期健康接口返回：

```json
{"status":"ok"}
```

## 6. 联调

```bash
curl -X POST \
  'http://127.0.0.1:8000/cgi-bin/webhook/send?key=<路由密钥>' \
  -H 'Content-Type: application/json' \
  -d '{"msgtype":"text","text":{"content":"镜像部署测试"}}'
```

成功：

```json
{"errcode":0,"errmsg":"ok"}
```

原推送服务替换为：

```text
https://router.example.com/cgi-bin/webhook/send?key=<路由密钥>
```

## 7. 升级与回滚

发布新版本镜像后，只修改 `.env` 中的 `ROUTER_IMAGE`：

```dotenv
ROUTER_IMAGE=<镜像仓库>/wecom-feishu-router:0.2.1
```

升级：

```bash
./deploy.sh
```

回滚时把 `ROUTER_IMAGE` 改回旧版本，再执行：

```bash
./deploy.sh
```

不要执行 `docker compose down -v`，否则会删除临时文件映射数据卷。

## 8. 排障

```bash
docker compose ps
docker compose logs --tail=200 router
docker compose config
```

- `pull access denied`：镜像地址错误、镜像未推送或服务器未登录私有仓库。
- 容器反复重启：检查 `.env` 必填变量和 JSON 格式。
- 文本成功但图片失败：检查飞书应用 ID、密钥和资源上传权限。
- 文件发送失败：检查 `FEISHU_CHAT_ID`、应用机器人是否在群内。
- 公网无法访问：保持端口绑定 `127.0.0.1`，通过 Nginx HTTPS 反向代理。
