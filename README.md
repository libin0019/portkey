# 企业微信 → 飞书群消息路由

这是一个兼容企业微信群机器人 Webhook 报文的 Python 服务。已有推送程序只需把
原企微 Webhook 替换为本服务地址，服务就会转换报文并投递到对应飞书群。

## 支持范围

| 企业微信消息 | 飞书投递方式 | 说明 |
| --- | --- | --- |
| `text` | 群自定义机器人 Webhook | 支持 `@all` 和成员 ID 映射 |
| `markdown` / `markdown_v2` | 群自定义机器人文本 | 保留原文 |
| `news` / `template_card` | 群自定义机器人文本 | 提取主要内容和链接 |
| `image` | 飞书应用上传 + 群 Webhook | 校验 Base64 和可选 MD5 |
| `file` | 飞书应用上传 + 应用机器人发送 | 需要目标群 `chat_id` |

## 镜像部署

生产 Compose 只引用远程镜像，不包含 `build:`，应用配置完全来自 `.env`，不再需要
挂载 `config.toml`：

```bash
cp .env.example .env
vi .env
docker compose pull
docker compose up -d
docker compose ps
```

发布镜像、生成部署包和服务器配置参见
[镜像仓库 Compose 部署手册](docs/REGISTRY_COMPOSE_DEPLOYMENT.md)。

## 单群环境变量

```dotenv
ROUTER_IMAGE=ghcr.io/libin0019/portkey:0.2.0
ROUTER_WEBHOOK_KEY=使用openssl生成的随机值
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_WEBHOOK_SECRET=
FEISHU_CHAT_ID=oc_xxx
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

- `FEISHU_WEBHOOK_SECRET` 仅在群自定义机器人启用签名时填写。
- 纯文本消息可以不填 `FEISHU_CHAT_ID`、`FEISHU_APP_ID` 和
  `FEISHU_APP_SECRET`。
- 图片需要飞书应用凭证；文件还要求应用机器人进入目标群并配置 `chat_id`。

## 多群环境变量

多群时删除 `ROUTER_WEBHOOK_KEY`，改用一行 JSON：

```dotenv
ROUTER_ROUTES_JSON='{"route-key-1":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/xxx","webhook_secret":"secret","chat_id":"oc_xxx"},"route-key-2":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/yyy","chat_id":"oc_yyy"}}'
```

`ROUTER_WEBHOOK_KEY` 与 `ROUTER_ROUTES_JSON` 不能同时配置。飞书应用凭证由所有路由
共用。

## Webhook 地址

发送消息：

```text
https://router.example.com/cgi-bin/webhook/send?key=<ROUTER_WEBHOOK_KEY>
```

上传文件：

```text
https://router.example.com/cgi-bin/webhook/upload_media?key=<ROUTER_WEBHOOK_KEY>&type=file
```

成功响应保持企微格式：

```json
{"errcode":0,"errmsg":"ok"}
```

## 本地构建

```bash
cp .env.example .env
vi .env
docker compose \
  -f docker-compose.yml \
  -f docker-compose.build.yml \
  up -d --build
```

检查：

```bash
curl http://127.0.0.1:8000/healthz
docker compose logs --tail=100 router
```

## 测试

```bash
pytest
```

测试使用模拟飞书接口，不会发送真实消息。
