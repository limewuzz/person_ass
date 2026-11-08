# 独立 PostgreSQL 提案（⚠ 未部署——P0-06 第 2 项被暂缓，本文件仅供评审）

状态：**PROPOSAL / NOT DEPLOYED** ｜ 提出日期 2026-11-08 ｜ 部署需用户单独批准

## 1. 隔离设计（回应评审要求：Docker 网络隔离 + 恢复方案先行）

### compose 设计（deploy/postgres/compose.yml.proposal）

- **镜像**：`postgres:16@sha256:e17e86066e5ef83e0952a9347f5c792b7ece00972e2aa787a6986f471b3dd3d5`
  ——与 rakazo-postgres-1 同 digest（宿主已缓存，无需重新拉取，规避出站故障风险）
- **网络**：自建 bridge `mwcp-internal`（internal: true，**无出站**）+ **不发布任何端口**
  （`ports:` 为空——后端容器同网络内以服务名 `mwcp-db:5432` 访问；宿主调试走 `docker exec`）
- **数据卷**：命名卷 `mwcp-pgdata`（独立于 rakazo 的卷，绝不挂载 rakazo 数据）
- **资源限额**：`mem_limit: 512m`、`cpus: 1.0`（预算依据 P0-03：宿主 available 5.9GiB，
  上限占比 <9%；rakazo PG 实测占用 102MiB，512m 有 5 倍余量）
- **重启策略**：`unless-stopped`（与现有容器策略一致）
- **凭据**：`POSTGRES_PASSWORD` 走 `/root/magicworkshop/control-plane/.env`（600 权限，
  **不进 git**）；首次部署生成随机 32 字节

### 与既有系统的隔离边界

| 维度 | rakazo-postgres-1（现有） | mwcp-db（提案） |
|---|---|---|
| 实例 | 独立容器 | 独立容器 |
| 网络 | br-9b8f0b0daa56（rakazo 内部） | mwcp-internal（新，internal） |
| 卷 | rakazo 系卷 | mwcp-pgdata（新） |
| 端口发布 | 127.0.0.1:5173/3100 同网其他容器 | **无任何发布** |
| role | rakazo | mwcp（新 role，仅对新库 ALL） |

## 2. 备份与恢复方案（部署前置条件）

- **备份**：宿主 cron（新 timer，**部署时单独申请**）：每日 03:30 UTC
  `docker exec mwcp-db pg_dump -U mwcp control_plane | gzip > /root/magicworkshop/control-plane/backups/db-$(date +%F).sql.gz`，
  保留 14 份轮转；每周一份异机拷贝到 Mac（经 mihomo 域名路由 scp，方向 Mac 拉取）
- **恢复演练（部署 Gate 必做）**：
  1. `gunzip -c db-X.sql.gz | docker exec -i mwcp-db psql -U mwcp -d control_plane_restore`
  2. 断言表计数/行数与源一致
  3. 记录 RPO=24h / RTO=15min（人工触发）
- **Alembic**：`db/` 迁移 up→down→up 三连过才允许碰生产库（001_control_plane.sql 转译）

## 3. Docker/UFW 实际隔离证据（P0 复核已采，2026-11-08 18:50）

- 现有 10 个容器端口绑定**全部 127.0.0.1**，DNAT 规则目标均为 `-d 127.0.0.1/32`
  （iptables-save nat 表逐条核验）→ 本提案「零发布」比现状更强
- ufw 默认 deny incoming + deny routed；宿主无全局 IPv6
- 外部双视点实测（UCloud+腾讯）：18085/18086/3010 CLOSED，23793/8443 OPEN（与 ufw 互证）
- 本提案落地后的验证清单：`docker inspect mwcp-db` 无 PortBindings + `ss -tlnp | grep 5432`
  为空 + 从 rakazo 容器内 `pg_isready -h mwcp-db` 失败（网络隔离生效证明）

## 4. 回滚

整目录 `/root/magicworkshop/control-plane/` + 卷 `mwcp-pgdata` + 网络 `mwcp-internal`
三者 `docker compose down -v` 即完全移除，不触碰 rakazo 任何资源。
