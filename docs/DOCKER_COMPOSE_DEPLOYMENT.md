# Docker Compose 部署说明

当前版本推荐使用远程镜像拉取和纯 `.env` 配置方式。

完整手册请参见：

- [镜像仓库 Docker Compose 部署手册](REGISTRY_COMPOSE_DEPLOYMENT.md)

服务器端核心命令：

```bash
docker compose pull
docker compose up -d
docker compose ps
```
