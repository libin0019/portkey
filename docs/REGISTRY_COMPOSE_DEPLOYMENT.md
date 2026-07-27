# 镜像仓库 Docker Compose 部署手册

本项目的生产部署只需要远程镜像、`docker-compose.yml` 和 `.env`，服务器无需保存
Python 源码，也不需要本地构建镜像。

## 1. 部署文件

从项目发布包中取得以下文件并放入同一目录：

```text
docker-compose.yml
.env
deploy.sh
```

也可以在项目目录生成拉取式部署包：

```bash
sh scripts/package-registry-deploy.sh ghcr.io/libin0019/portkey:0.3.0
```

生成：

```text
dist/wecom-feishu-router-0.3.0-compose-pull.tar.gz
dist/wecom-feishu-router-0.3.0-compose-pull.tar.gz.sha256
```

上传 EC2：

```bash
scp dist/wecom-feishu-router-0.3.0-compose-pull.tar.gz* \
  ubuntu@<EC2公网IP>:/tmp/
```

在服务器解压：

```bash
cd /tmp
sha256sum -c wecom-feishu-router-0.3.0-compose-pull.tar.gz.sha256
sudo mkdir -p /opt/wecom-feishu-router
sudo tar -xzf wecom-feishu-router-0.3.0-compose-pull.tar.gz \
  -C /opt/wecom-feishu-router \
  --strip-components=1
sudo chown -R "$(id -un):$(id -gn)" /opt/wecom-feishu-router
cd /opt/wecom-feishu-router
```

GHCR Package 为 Public 时不需要登录，服务器可直接拉取。

## 2. 动态 Webhook 配置

编辑 `.env`：

```bash
vi .env
chmod 600 .env
```

仅转发文本的完整示例：

```dotenv
COMPOSE_PROJECT_NAME=wecom-feishu-router
ROUTER_IMAGE=ghcr.io/libin0019/portkey:0.3.0
ROUTER_BIND_IP=127.0.0.1
ROUTER_PORT=8000
LOG_LEVEL=INFO

DYNAMIC_WEBHOOK_ENABLED=true
FEISHU_WEBHOOK_BASE_URL=https://open.feishu.cn/open-apis/bot/v2/hook
DYNAMIC_WEBHOOK_SECRET=
DYNAMIC_MENTION_MAP_JSON={}

FEISHU_APP_ID=
FEISHU_APP_SECRET=

SQLITE_PATH=/app/data/router.db
MEDIA_TTL_SECONDS=259200
MAX_IMAGE_BYTES=10485760
MAX_FILE_BYTES=20971520
MAX_REQUEST_BYTES=25165824
MAX_CONCURRENT_MEDIA_OPERATIONS=4
REQUEST_TIMEOUT_SECONDS=15
```

动态模式会从请求参数 `key` 中取得飞书 Webhook 标识，并与
`FEISHU_WEBHOOK_BASE_URL` 自动拼接。基地址只能使用以下两种官方 V2 地址：

```text
https://open.feishu.cn/open-apis/bot/v2/hook
https://open.larksuite.com/open-apis/bot/v2/hook
```

如果群机器人开启签名校验，并且所有动态路由使用同一个密钥：

```dotenv
DYNAMIC_WEBHOOK_SECRET=群机器人签名密钥
```

如果不同群机器人使用不同签名密钥，不能使用一个全局动态密钥，应为这些机器人
配置静态路由。

成员映射示例：

```dotenv
DYNAMIC_MENTION_MAP_JSON='{"zhangsan":"ou_xxx"}'
```

## 3. 图片和文件配置

图片需要飞书应用先上传图片，因此要同时填写：

```dotenv
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=应用密钥
```

文件消息除了应用凭证，还需要目标群 `chat_id`。Webhook 标识无法推导 `chat_id`，
所以文件路由必须使用静态配置。例如在保留动态模式的同时增加一个文件路由：

```dotenv
DYNAMIC_WEBHOOK_ENABLED=true
FEISHU_WEBHOOK_BASE_URL=https://open.feishu.cn/open-apis/bot/v2/hook

ROUTER_WEBHOOK_KEY=file-route
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_WEBHOOK_SECRET=
FEISHU_CHAT_ID=oc_xxx

FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=应用密钥
```

多个文件群或不同签名密钥使用一行 JSON，并删除
`ROUTER_WEBHOOK_KEY`、`FEISHU_WEBHOOK_URL`、`FEISHU_WEBHOOK_SECRET` 和
`FEISHU_CHAT_ID`：

```dotenv
ROUTER_ROUTES_JSON='{"file-route-1":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/xxx","webhook_secret":"secret1","chat_id":"oc_xxx"},"file-route-2":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/yyy","chat_id":"oc_yyy"}}'
```

静态 key 命中时优先使用静态配置；其他合法 key 继续走动态拼接。

## 4. 启动

部署包可直接执行：

```bash
./deploy.sh
```

等效 Docker Compose 命令：

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

健康接口预期返回：

```json
{"status":"ok"}
```

## 5. 改造推送地址

假设飞书群机器人 Webhook 是：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/f99fed8d-9b01-4dfe-ab56-123456789abc
```

自动截取最后一段：

```text
f99fed8d-9b01-4dfe-ab56-123456789abc
```

把原推送服务地址改为：

```text
https://router.example.com/cgi-bin/webhook/send?key=f99fed8d-9b01-4dfe-ab56-123456789abc
```

路由服务自动拼接并请求原飞书 Webhook。`key` 也可传完整地址，但必须先做 URL
编码；生产配置推荐只传最后一段标识。

联调文本：

```bash
curl -X POST \
  'http://127.0.0.1:8000/cgi-bin/webhook/send?key=f99fed8d-9b01-4dfe-ab56-123456789abc' \
  -H 'Content-Type: application/json' \
  -d '{"msgtype":"text","text":{"content":"动态 Webhook 部署测试"}}'
```

成功响应：

```json
{"errcode":0,"errmsg":"ok"}
```

## 6. Nginx 反向代理

Docker 默认只监听 `127.0.0.1:8000`。公网访问建议由 Nginx 提供 HTTPS，参考部署
包中的 `nginx.conf.example`。由于 URL 中含 Webhook 标识，不要记录该接口的访问
日志，也不要把完整请求地址写入监控或工单。

## 7. 升级与回滚

发布新版本后，只修改 `.env` 中的镜像标签：

```dotenv
ROUTER_IMAGE=ghcr.io/libin0019/portkey:0.3.1
```

执行：

```bash
./deploy.sh
```

回滚时改回旧标签后再次执行。不要执行 `docker compose down -v`，否则会删除文件
映射所使用的数据卷。

## 8. 排障

```bash
docker compose ps
docker compose logs --tail=200 router
docker compose config
```

- `pull access denied`：镜像地址错误、Package 不是 Public 或服务器未登录仓库。
- 容器反复重启：检查 `.env` 布尔值、必填变量和 JSON 格式。
- `无效的飞书 Webhook 标识`：`key` 不是 16 至 128 位合法标识，或包含路径字符。
- 文本成功但图片失败：检查应用 ID、密钥以及图片上传权限。
- 文件发送失败：改用包含 `chat_id` 的静态路由，并确认应用机器人已进入目标群。
- 公网无法访问：检查 Nginx、HTTPS 证书、安全组和反向代理地址。
