# 独立 PostgreSQL 提案 v2（⚠ 未部署——评审中，部署需用户单独批准）

状态：**PROPOSAL v2 / NOT DEPLOYED** ｜ 2026-11-08 ｜ 本版按 P0 评审 §E 六点逐项修订

## 0. v1 → v2 修订摘要（对应评审意见）

| 评审意见 | v2 修订 |
|---|---|
| ① 网络拓扑：PG 在 internal 网络且不发布端口时，宿主回环上的 FastAPI 连不上 | 改为**双服务 Compose**：`mwcp-db`（仅 mwcp-internal）+ `mwcp-api`（同时接 mwcp-internal 与默认桥，仅它发布 `127.0.0.1:8123`）。API 经 Compose 内置 DNS 服务名 `mwcp-db:5432` 连库，**不依赖容器动态 IP**。宿主上不再运行裸 FastAPI，因此不存在「宿主连不上 internal PG」的矛盾 |
| ② `down -v` 不是回滚（会删卷） | 回滚章节重写：**停止保留卷**（`docker compose stop` / `down`（不带 -v））；删卷列为**独立审批项**，SOP 中显式红色标注 |
| ③ 备份要有恢复证据 | 新增「备份与恢复 SOP」：pg_dump（单库）+ `pg_dumpall --globals-only`（角色/表空间等集群对象，弥补 pg_dump 盲区）、权限 600、openssl AES-256 加密后异机、月度恢复演练步骤与通过标准、失败告警通道 |
| ④ 限额与运行设置 | 显式 PG 参数（shared_buffers/max_connections/work_mem/log_min_duration）、OOM 行为说明、健康探针、digest 锁定与架构确认 |
| ⑤ 隔离与凭据 | 对比表更新（与 rakazo 的 project/网络/卷/端口/备份全不重叠）；口令只经 `.env`（600，不入 compose 文本、不入 git）|
| ⑥ 首次部署门槛 | 前置检查清单：`docker compose config` 静态校验（占位口令本地演练）、env 展开脱敏检查、一键只停新服务的命令验证 |

## 1. 拓扑（v2 核心）

```
宿主（美国服务器，仅回环暴露）
  └─ 127.0.0.1:8123 ──> mwcp-api 容器（FastAPI/uvicorn）
                          ├─ 网络1: mwcp-internal（internal:true，无出站网关）
                          │    └─ mwcp-db:5432（DNS 服务名解析，PG 不发布任何端口）
                          └─ 网络2: mwcp-edge（普通桥，仅用于将来受控出站探针；
                               P1 阶段可不接——见 compose 注释，默认只接 internal）
```

- **PG 从任何宿主端口、任何公网地址均不可达**（无 ports 发布 + internal 网络双重保证）。
- 宿主调试路径：`docker exec mwcp-db psql -U mwcp -d control_plane`（审计可查、显式留痕），不开放网络路径。
- 与 UCloud 入口的将来对接：nginx（宿主）→ 127.0.0.1:8123 → mwcp-api，**属独立审批项，本提案不含**。

## 2. compose.yml.proposal（同目录文件，脱敏原文）

要点：postgres:16 同 rakazo digest（宿主已缓存、amd64 架构与宿主一致）；`stop_grace_period: 90s`（PG 优雅关库）；
`mem_limit: 512m, cpus: 1.0`；healthcheck `pg_isready`（10s×5）；`restart: unless-stopped`。
PG 参数（命令行注入，不建 postgresql.conf 依赖）：
`shared_buffers=128MB max_connections=50 work_mem=4MB effective_cache_size=256MB log_min_duration_statement=500ms`
（512MiB 容器内预算自洽：128MB 共享内存 + 50 连接×(工作集~4-8MB 峰值) + 进程开销，达到上限时新连接被拒而非 OOM；
OOM 若仍发生，容器重启由 unless-steward 策略拉起，数据经 WAL 崩溃恢复——此行为在部署 Gate 演练确认。）

## 3. 回滚定义（v2 重写）

| 动作 | 命令 | 卷 | 说明 |
|---|---|---|---|
| **停止（标准回滚）** | `docker compose -p mwcp stop` | **保留** | 服务消失、数据保留，重启即恢复 |
| 下线（保留数据） | `docker compose -p mwcp down`（无 -v） | **保留** | 容器/网络删除，卷与数据留存 |
| 🔴 **销毁数据卷** | `docker compose -p mwcp down -v` | **删除** | **数据销毁，非回滚！须用户单独明确授权，且要求先完成一次全量备份并验证可恢复** |

一键只停新服务（不影响 rakazo 等）：`docker compose -p mwcp -f /root/magicworkshop/control-plane/deploy/postgres/compose.yml stop`
（Compose project 名 `mwcp` 与 rakazo 的 project、网络、卷命名空间完全隔离——对比表见 §5。）

## 4. 备份与恢复 SOP（v2 新增，评审 ③）

- **内容**：每日 03:30 UTC ① `pg_dump -Fc control_plane`（单库逻辑）② `pg_dumpall --globals-only`（角色/表空间/数据库目录——pg_dump 盲区）；每周日全量双份。
- **权限**：备份目录 `/root/magicworkshop/control-plane/backups/` 属主 root、`700`；文件 `600`；umask 077。
- **加密与出网**：异机前 `openssl enc -aes-256-cbc -pbkdf2` 加密（口令经 Mac 钥匙串管理的环境注入，不落盘明文）；传输方向 **Mac 主动拉取**（mihomo 域名路由），不上推。
- **保留**：本地 14 份日备 + 4 份周备；Mac 侧 8 份周备（加密）。
- **恢复演练（每月，部署 Gate 首跑）**：
  1. 起临时容器 `mwcp-restore-test`（同镜像，独立卷）
  2. `pg_restore -d control_plane < dump` + globals 导入
  3. 通过标准：表数量一致、关键表行数一致、001 迁移版本号一致
  4. 演练产物（时间/命令/计数对比）归档 `docs/restore-drills/`
- **RPO/RTO**：RPO=24h（日备）；RTO=15min（人工触发，恢复演练度量）。
- **失败告警**：备份脚本失败 → 写宿主 `/root/magicworkshop/control-plane/backups/FAILED` 标记 + Mac 心跳通道通知（复用 daily-assistant heartbeat 模式的只读通知位，不改现有服务）。**告警通道属新增调度，部署时单独申请。**

## 5. 与 rakazo PostgreSQL 隔离对比

| 维度 | rakazo-postgres-1 | mwcp-db（提案） |
|---|---|---|
| Compose project | rakazo | mwcp |
| 网络 | rakazo_app/rakazo_data | mwcp-internal（internal:true） |
| 卷 | appdata 等（rakazo 系） | mwcp-pgdata（独立命名） |
| 宿主端口 | 127.0.0.1:5173/3100（同 project 其他容器） | **无** |
| role/库 | rakazo/rakazo | mwcp/control_plane |
| 备份 | 无（审计记录） | 本 SOP |
| 资源 | 2GiB 上限（compose） | 512MiB |

## 6. 首次部署 Gate（未到，列门槛）

1. 本地 `docker compose -f compose.yml.proposal config` 静态校验（占位口令，Mac 无 docker——部署前在美国机执行，输出脱敏后存档）
2. env 展开 diff 检查：`docker compose config --no-interpolate` vs interpolate，确认无口令入 compose 渲染文本
3. 一键停止命令演练（对已运行的 rakazo 零影响证明）
4. 用户**新一轮明确批准**（范围=起容器+建卷+接 internal 网络；不含任何 nginx/公网/迁移）
