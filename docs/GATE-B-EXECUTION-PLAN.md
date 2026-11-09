# GATE-B 隔离实验方案（等待用户批准——本轮零执行）

**状态：PLAN_ONLY / NOT_RUN。** 未获用户对下列 §A–§G 的逐项批准前，不启动 Docker、不启动 PostgreSQL、不连接任何真实数据库、不创建任何卷/网络/容器。

## A. 实验环境（三选一，用户指定）

| 方案 | 位置 | 隔离度 | 优点 | 缺点 |
|---|---|---|---|---|
| **A1（推荐）** | Mac mini 本地：colima（当前未装）或 OrbStack | 完全隔离，零生产接触 | 可反复跑、清理零残留 | 需装容器运行时（~500MB 磁盘）；非 Linux x86_64（PG 行为基本一致，内核差异小） |
| A2 | Mac mini：uv 管理的 postgresql@16 二进制（免 Docker） | 进程级隔离（仅回环 127.0.0.1:5499） | 无容器依赖 | 非容器化——清理靠 stop+rm 数据目录 |
| A3 | 美国服务器：独立 docker network+独立卷+独立容器 | 网络级隔离（`internal:true`，零端口发布） | 与生产同架构/同 OS | **生产宿主**——需最高级别授权+资源确认 |

**A3 网络拓扑**：`mwcp-gateb-net`（`internal:true`，无出站）——`mwcp-gateb-pg`（不发布端口）+ 可选 `mwcp-gateb-app`（`127.0.0.1:8129:8127` 仅回环）；与 rakazo/app_coco 的网络/卷/容器名零交集（前置检查命令清单见 §G）。

## B. PostgreSQL 版本与镜像

- **版本**：PostgreSQL 16
- **镜像 digest**：`postgres:16@sha256:e17e86066e5ef83e0952a9347f5c792b7ece00972e2aa787a6986f471b3dd3d5`（与宿主 rakazo-postgres-1 同 digest——Gate B 实验用独立拉取验证 digest 一致性；部署 Gate 时锁宿主架构 digest）
- 配置：`shared_buffers=128MB max_connections=20 work_mem=2MB shm_size=256m mem_limit=640m`（与 PG v5 提案一致）

## C. 端口/网络/卷

| 项 | 值 |
|---|---|
| PG 监听 | 仅容器网络内部（`internal:true`）——**零宿主端口发布** |
| 应用（如装） | `127.0.0.1:8129→8127`（仅回环） |
| 卷 | `mwcp-gateb-pgdata`（实验结束整体删除——见 §G） |
| 网络 | `mwcp-gateb-net`（internal:true，实验结束删除） |

## D. 测试凭据

- 生成：`openssl rand -base64 32` × 3（bootstrap/migrator/app），**直写**实验机 `deploy/postgres/secrets/`（0600，root）——不经对话/日志/git
- 实验结束：secrets 目录随数据卷一起销毁；凭据**不复用**到任何其他环境

## E. 测试矩阵（通过标准=全部绿才可关 Gate B）

| # | 测试 | 命令/方法 | 通过标准 |
|---|---|---|---|
| E1 | 迁移 0001→0002 干净执行 | MigrationRunner.apply ×2 | schema_migrations 有 2 行；表全建 |
| E2 | 迁移回滚（down） | 手写 0002.down（drop leases/artifacts）+ 0001.down（drop all）| 版本表清空；重建再迁移 → 一致 |
| E3 | 幂等 100 并发 | 100 线程 INSERT ON CONFLICT | **恰好 1 行** |
| E4 | 任务状态 CAS | 并发 transition A→B 两写者 | 恰好一个成功 |
| E5 | generation ABA | bump→bump（expected 旧值） | 第二次 generation conflict |
| E6 | 审批一次性消费 | 并发 consume_once ×2 | 恰好一个 consumed |
| E7 | 审批 payload 篡改 | consume(hash≠approved hash) | 0 行=拒绝 |
| E8 | 租约过期迟到 finish | expire lease → finish(generation=旧) | 0 行=迟到拒绝 |
| E9 | 权限负向（app 角色禁 DDL） | `perm-negative-tests.sql` 以 mwcp_app 执行 | CREATE TABLE/DROP TABLE/CREATE ROLE 全 ERROR: permission denied |
| E10 | 权限正向（migrator DDL / app DML） | 建表→INSERT/SELECT | 全通 |
| E11 | 崩溃/重启持久化 | `docker kill -9` PG → 重启 → recovery_on_restart | 任务/审批/审计全存活；过期租约→NEEDS_RECONCILIATION |
| E12 | 备份恢复 | `pg_dump -Fc` + globals → 全新卷 restore → E1 重跑 | 对象/行数/权限一致 |
| E13 | 备份加密完整性 | openssl AES-256 + HMAC | 恢复前验签必过；篡改一字节必败 |
| E14 | OOM/资源 | memory stress → 观察 cgroup 限制行为 | PG 容器被限制不拖垮 rakazo；恢复后 WAL 无损坏 |
| E15 | pgbench 压测 | `-c 20 -j 4 -T 300` | 完成；记录 tps/RSS/磁盘增长 |
| E16 | 回环/非回环 | 宿主 `curl 127.0.0.1:8129` 200；外部 IP 连接拒绝 | 仅回环可达 |

## F. 资源限制

- PG 容器：`mem_limit=640m cpus=1.0 shm_size=256m`；app：`mem_limit=256m`
- OOM 退出标准：PG OOM-restart 后 WAL 崩溃恢复无损坏 + 数据零丢失（E11/E14 联合验证）；app OOM → restart 拉起后 ready 正常
- 磁盘预算：实验卷 ≤2GB；宿主剩余 ≥50GB 前置检查

## G. 清理与回滚（实验失败或结束）

```bash
# 一键清理（仅 mwcp-gateb-* 前缀——绝不触及 rakazo/生产）
docker compose -p mwcp-gateb -f deploy/postgres/compose-gateb.yml down -v  # ⚠-v 仅在确认销毁数据后
docker network rm mwcp-gateb-net; docker volume rm mwcp-gateb-pgdata
rm -rf deploy/postgres/secrets/  # 凭据同灭
# 前置零干扰断言（实验前后各跑一次）
docker ps -a --filter name=rakazo --format '{{.Names}} {{.Status}}'  # 前后一致
docker stats --no-stream rakazo-postgres-1  # 前后 RSS 差 <5%
```

## H. 需要用户批准的清单（本方案零自决）

1. 实验环境选择（A1/A2/A3）
2. 若 A3：批准在美国宿主创建 `mwcp-gateb-*` 容器/网络/卷（名称、限额如上）
3. 测试窗口（建议避开 bot 例行 01:15/09:30/21:30 前后 30 分钟——仅 A3 相关）
4. 凭据生成方式确认（本地 openssl 随机、不经对话）
5. 实验结束后的销毁确认（down -v + secrets rm）
