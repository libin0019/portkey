# 企业微信 → 飞书群消息路由

这是一个兼容企业微信群机器人 Webhook 报文的 Python 服务。已有推送程序只需把
原企微地址替换为本服务地址，并把 `key` 换成飞书群机器人 Webhook 的标识，服务会
自动拼接飞书请求地址并完成消息转换。

## 动态 Webhook

飞书群机器人地址示例：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/f99fed8d-9b01-4dfe-ab56-123456789abc
```

截取最后一段 Webhook 标识，并把原推送地址改成：

```text
https://router.example.com/cgi-bin/webhook/send?key=f99fed8d-9b01-4dfe-ab56-123456789abc
```

路由服务会自动请求：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/f99fed8d-9b01-4dfe-ab56-123456789abc
```

`key` 也兼容传入经过 URL 编码的完整飞书 Webhook 地址。动态模式只允许拼接
`open.feishu.cn` 或 `open.larksuite.com` 的 V2 官方地址，并会拒绝其他主机、
额外路径、查询参数和无效标识。

## 支持范围

| 企业微信消息 | 飞书投递方式 | 动态模式说明 |
| --- | --- | --- |
| `text` | 群自定义机器人 Webhook | 直接支持 |
| `markdown` / `markdown_v2` | 群自定义机器人文本 | 保留原文 |
| `news` / `template_card` | 群自定义机器人文本 | 提取主要内容和链接 |
| `image` | 飞书应用上传 + 群 Webhook | 需要应用凭证 |
| `file` | 飞书应用上传 + 应用机器人发送 | 必须配置含 `chat_id` 的静态路由 |

飞书 Webhook 标识本身不能换算成 `chat_id`，因此文件消息不能只使用动态路由。

## Docker Compose 部署

```bash
cp .env.example .env
vi .env
docker compose pull
docker compose up -d
docker compose ps
```

默认动态模式的核心配置：

```dotenv
ROUTER_IMAGE=ghcr.io/libin0019/portkey:0.3.0
DYNAMIC_WEBHOOK_ENABLED=true
FEISHU_WEBHOOK_BASE_URL=https://open.feishu.cn/open-apis/bot/v2/hook
DYNAMIC_WEBHOOK_SECRET=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

- 只转发文本时，飞书应用 ID 和密钥保持为空。
- 转发图片时，同时填写 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。
- 所有动态机器人共用签名密钥时填写 `DYNAMIC_WEBHOOK_SECRET`；各机器人密钥不同
  时应使用静态路由。
- Lark 国际版把基地址改为
  `https://open.larksuite.com/open-apis/bot/v2/hook`。

完整服务器操作参见
[镜像仓库 Compose 部署手册](docs/REGISTRY_COMPOSE_DEPLOYMENT.md)。

## 静态路由兼容

原有单路由变量仍然有效，并且优先于动态路由：

```dotenv
DYNAMIC_WEBHOOK_ENABLED=true
ROUTER_WEBHOOK_KEY=file-route
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_WEBHOOK_SECRET=xxx
FEISHU_CHAT_ID=oc_xxx
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

多群且需要独立签名密钥或 `chat_id` 时使用：

```dotenv
ROUTER_ROUTES_JSON='{"file-route":{"webhook_url":"https://open.feishu.cn/open-apis/bot/v2/hook/xxx","webhook_secret":"secret","chat_id":"oc_xxx"}}'
```

`ROUTER_WEBHOOK_KEY` 与 `ROUTER_ROUTES_JSON` 不能同时配置，但两种静态配置都可以
和动态模式共存。

## 接口

发送消息：

```text
POST /cgi-bin/webhook/send?key=<飞书Webhook标识>
```

上传文件：

```text
POST /cgi-bin/webhook/upload_media?key=<静态路由key>&type=file
```

成功响应保持企微格式：

```json
{"errcode":0,"errmsg":"ok"}
```

## 本地构建与测试

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.build.yml \
  up -d --build
pytest
```

测试使用模拟飞书接口，不会发送真实消息。
