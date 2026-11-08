# 独立 PostgreSQL 提案（⚠ 未部署——评审中，部署需用户新一轮明确批准）

## v5 变更（R5-D1/D2/D3/D4 修复，对应 GPT-6 独立评审 §5）
- D1 **角色顺序**：`init/00-init-roles.sh` 重写——先 CREATE 两个角色，后 GRANT/ALTER DEFAULT PRIVILEGES（原顺序在空集群必失败）
- D2 **构建上下文**：compose `context: ../..`（仓库根）+ `dockerfile: backend/Dockerfile.api`，全部 COPY 源路径经独立测试逐项存在性验证
- D3 **密码不进 argv**：删除 `psql -v` 传参，改为 heredoc stdin + SQL 转义（进程参数/日志/环境展开均无明文）
- D4 **API secret 接通**：entrypoint 只传 `MWCP_AUTH_SECRETS_FILE`/`MWCP_PG_APP_PASSWORD_FILE` 路径（不再写临时明文 env 文件、变量正确 export）；`auth.load_secrets_from_env()` 优先读文件（功能测试覆盖）；readiness 的 database 仍诚实 `not_connected`（P1-03 前不得宣称 ready）
- 静态证据：`compose-v5.yml.proposal`（=修复后 v4 内容正名版；v4 文件保留且同步修复供 GPT-6 测试路径引用）


状态：**PROPOSAL v3 / NOT DEPLOYED** ｜ 2026-11-08 ｜ 本版按 R2 评审 BLOCK-01~06 逐项修订
文件：`compose-v3.yml.proposal`（本目录）、`init-roles.sql`；v2 文件保留供对照但已作废。

## 0. v2 → v3 修订对照

| 评审阻断项 | v3 修订 |
|---|---|
| BLOCK-01 凭据经 env 展开（config/inspect 泄露） | 全部改**文件型 Compose secrets**（/run/secrets）；PG 用 `POSTGRES_PASSWORD_FILE`；API 的 DSN/JWT 密钥改为启动时从 secret 文件进程内拼装，**compose env 段零口令零 DSN**；静态校验用 `config --quiet`（渲染配置不入工单）+ 部署后 `docker inspect` 抽查无明文 |
| BLOCK-02 应用连库是超级用户 | 三账户拆分：`mwcp_bootstrap`（镜像引导，首启后 NOLOGIN）→ `mwcp_migrator`（仅 DDL/Alembic）→ `mwcp_app`（仅 DML+序列，NOSUPERUSER/NOCREATEDB/NOCREATEROLE）——`init-roles.sql` 落地 |
| BLOCK-03 恢复顺序/标准/指标 | 恢复 SOP 重写（§4）：**完整性格式校验 → globals 先行（独立测试集群）→ 建库 → pg_restore --exit-on-error → 对象/行数/权限抽测 → 应用只读连接 → 故障注入**；RPO/RTO 降级为「目标值，演练前不宣称 SLA」 |
| BLOCK-04 加密无完整性 | 首选 `age`（内建认证加密）；openssl 路线则 AES-256-CBC **+独立 HMAC-SHA256 校验文件**，恢复前强制验签 |
| BLOCK-05 内存预算断言不成立 | 承认错误公式；给出诚实的最坏情况公式 + `shm_size=256m` 显式 + `max_connections=20` 收紧 + **pgbench 压测 Gate**（未压测不定案）；`work_mem` 语义修正（单会话可多次分配） |
| BLOCK-06 全局名/首启 Gate | `container_name`/卷名冲突前置检查命令；回环可达性在**目标 Docker 版本实测**；`mwcp-edge` 未创建（未来独立审批带资源清单）；OOM 恢复行为列入故障注入演练 |

## 1. 拓扑（不变，v2 已通过）

`127.0.0.1:8123 → mwcp-api（唯一宿主面）⇄ mwcp-internal(internal:true) ⇄ mwcp-db（零端口发布）`。
宿主调试仅 `docker exec`；接公网反代=未来独立审批。

## 2. 凭据与密钥管理（v3 核心）

| Secret 文件（部署机 ./secrets/，600，root） | 消费方 | 说明 |
|---|---|---|
| mwcp_pg_bootstrap_password | PG 镜像引导（POSTGRES_PASSWORD_FILE） | 首启后 ALTER ROLE mwcp_bootstrap NOLOGIN |
| mwcp_pg_migrator_password | init-roles.sql 注入 mwcp_migrator | Alembic 迁移时使用 |
| mwcp_pg_app_password | API 进程内拼 DSN | mwcp_app 运行账户（URL 特殊字符经转义，不拼裸串） |
| mwcp_auth_secrets | API Mock JWT kid 表 | 替代 v2 的 env 注入 |

- 生成：部署机 `openssl rand -base64 32` 直写文件；GLM/工单/日志不接触明文。
- 校验链：`docker compose config --quiet`（不落渲染文本）→ 起容器后 `docker inspect mwcp-db --format '{{.Config.Env}}'` 与 `mwcp-api` Env 抽查必须无任何口令/DSN 值。

## 3. 最小权限模型

见 `init-roles.sql` 注释：bootstrap（一次性，之后 NOLOGIN）/ migrator（DDL）/ app（DML+序列）。迁移产生的默认权限由 Alembic 迁移脚本内 GRANT（进版本控制，可审计）。**不使用、不触碰 Rakazo 的账号与库。**

## 4. 备份与恢复 SOP（v3，顺序修正）

备份（每日 03:30 UTC，新增调度=独立审批项）：
1. `pg_dump -Fc -d control_plane`（单库）
2. `pg_dumpall --globals-only`（角色/表空间；**同级加密保护**——含角色口令散列）
3. 完整性：`age -r <recipient> backup.dump > backup.dump.age`（认证加密）；openssl 备选路线追加 `.hmac`（HMAC-SHA256，密钥独立于加密口令）
4. 权限 700/600；Mac 拉取异机（同 v2）

恢复（**空白目标集群**演练，月度）：
1. 备份完整性格式校验（age 解封验签 / HMAC 比对）
2. **先 globals**：`psql -f globals.sql`（仅独立测试集群；作用域隔离）
3. 建库：`createdb -T template0 control_plane`
4. `pg_restore --exit-on-error --dbname=control_plane backup.dump`
5. Alembic 版本核对 + 对象计数/关键表行数/权限抽测（mwcp_app 能 SELECT、不能 DROP）
6. 应用以 mwcp_app 只读连接检查（/health/ready → database=ok）
7. 故障注入：kill -9 PG 容器 → unless-stopped 拉起 → WAL 崩溃恢复无损坏断言；OOM 模拟（memory stress）→ 容器行为记录
8. 全程产物归档 `docs/restore-drills/<date>.md`（无秘密值）

**RPO=24h / RTO=15min 为目标值；首次实弹演练完成前不作为 SLA 宣称。**

## 5. 资源预算（诚实版公式 + 压测 Gate）

最坏情况估算（非承诺）：`shared_buffers(128M) + shm(256m 上限，含锁/进程内共享) + 连接(20 × (work_mem 可多次分配：排序/哈希节点数 n × 2M + 每连接基础 ~5-10M)) + WAL/维护/文件缓存`。
→ 20 连接重度查询最坏 ~128+200+20×(4×2+10)≈**508M** → mem_limit 取 **640m** 留缓冲；
**最终值必须以 pgbench Gate 实测定**：`pgbench -c 20 -j 4 -T 300`（小数据量）+ 观察 docker stats 峰值与 OOM 事件，未压测不冻结参数。压测只跑在 mwcp 独立容器，宿主 Rakazo 零影响（cgroup 隔离验证：压测期间 `docker stats rakazo-postgres-1` 无异常）。

## 6. 首次部署 Gate（顺序清单）

1. 名字冲突预检：`docker ps -a --filter name=mwcp-`、`docker volume ls -q | grep mwcp`、`docker network ls | grep mwcp` 全空
2. secret 文件生成与权限检查（600、root）
3. `docker compose -f compose-v3.yml.proposal -p mwcp config --quiet`（占位 secret 本地演练过；真实渲染不落盘）
4. 起容器 → `docker inspect` 双容器 Env 无口令断言
5. 回环可达性实测：宿主 `curl 127.0.0.1:8123/health/live` 200；从非回环接口访问拒绝（目标 Docker 版本实测，不以 YAML 推断）
6. init-roles 生效断言：`\du` 显示三角色权限正确
7. Alembic up/down/up 三连（staging 卷）
8. pgbench 压测 + OOM 注入（§5）
9. **用户新一轮明确批准**（范围：起容器/建卷/接 internal 网；不含 nginx/公网/迁移生产数据）
