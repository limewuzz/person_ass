# V2 Gate B：整改后执行交接

**PG_RUNTIME=NOT_RUN / DEPLOYED=NO / DEPLOYMENT_BLOCKED。** 本文取代旧 `GATE-B-EXECUTION-PLAN.md` 的操作部分；旧文件已归档至 `docs/archive/GATE-B-EXECUTION-PLAN.md` 作为历史记录。Gemini Canvas 清单正文未取得，本文件以受校验的 V2 源码和本轮修复为准。

## 版本与隔离

- 起点：Drive FullStack ZIP SHA `313a87f6cfd5e18336f0eb676a3072f38941d6b01b951f898f9740954733c2c6`；原始 tree `24ac3b87b5b4f2c51ea4e859f5d349fc4e1ea2e3`。ZIP 宣称 commit `ccd867c2ee400918c38587bc5dc30b31521ad111`，但正式远端未找到该分支；本轮把相同 tree 导入以 `ae654d4` 为父的提交，保留正式历史。
- 唯一活动契约仍为 `contracts/openapi.yaml`：2.0.0-unified-v2 / 79 paths / 95 operations，SHA `d94462c44cd7c331470fc79731da29a7539d78f770b52288fce590ae3f52504f`。本轮未改变接口定义。
- 本轮只授权本地代码、测试和交接。运行 PG/Docker、使用美国宿主、部署生产均未执行，仍须用户另行授权。
- 推荐 Gate B 在独立实验机或 VM。若用户明确指定美国宿主，先批准窗口及 CPU/内存/磁盘限制，不接入任何旧业务网络/卷/数据库，不修改代理、cron、DNS、旧服务或凭据。
- 只使用新 `deploy/postgres/compose-gateb.yml`，不要复制旧 v5 proposal。PG 无宿主端口，网络 internal，API 仅发布 127.0.0.1:8129，容器/卷/网络由 mwcp-gateb 项目命名，没有固定全局 container_name/volume.name。

## API 的真实持久化方式与边界

本轮保留已验证的域状态机，以 `runtime_state` 的版本化 JSONB 检查点作为当前 API 的唯一持久权威。每个 API 请求先取得 PG 行锁、装载最新状态，执行原有任务/审批/Worker/注册/V2 逻辑，再通过 revision CAS 写入同一事务，提交成功后才发送响应。失败不确认成功；回滚并恢复进程状态。多 API 进程也由同一行锁串行化。

这是单用户、有限状态量的明确选择：不另写一套与内存状态机不同的业务规则。`dbpg/repository.py` 中现有规范化表仓储继续提供独立接口和迁移验证，但**不是此 API runtime 的第二套数据源**。因此不能用 `SELECT * FROM tasks` 是否有行来代替 API 持久化验收；检查点、重启后 API 内容和审计必须一致。未来切换到规范化模型需显式迁移，禁止双写后不做一致性验证。

- 检查点 codec=1，仅允许显式名单内记录与字段，拒绝 pickle、动态类导入和未知版本。
- JSON 文档上限 64 MiB，单次缓冲响应上限 24 MiB；超限拒绝提交。当前 SSE 为有限快照，不是无限连接；将来持续 SSE 必须另设读事务。
- Provider 密钥、JWT 签名密钥、进程锁/连接及浏览器 session 不写检查点。重启后 session 失效；生产身份/跨进程 session 尚未验收。
- 上传内容保存在受限检查点中；适用于本地轻量控制平面，不适合大文件库。接近上限前应停止写入并规划独立 blob 存储，不能解除上限绕过容量验证。
- 不提供自动生产 PG 连接。`pg_runtime:create_app` 仅接受隔离 DNS `mwcp-gateb-pg`、mwcp_app/control_plane，以及显式 Gate B 授权环境；缺迁移/校验和错误/连接失败则停止，不能退回 memory。
- `/health/ready` 依据真实数据库检查报告依赖，但生产探针/身份/Worker 未接通时仍保持 503。不得直接改为 200。

## 授权后的准备命令（本轮未执行）

以下命令仅供 GLM 在用户批准隔离实验后执行。环境开关本身不是授权。先记录批准依据、实验机身份、源码 commit/tree、契约 SHA、运行依赖和镜像架构/digest。

```bash
export MWCP_GATE_B_AUTHORIZED=1
export MWCP_GATEB_SECRETS=/run/mwcp-gateb/secrets
# 已批准的实验宿主；此命令需 root，以设置容器实际读取 UID。
python3 scripts/gateb_secrets.py --authorized-isolated-gate-b
docker compose -p mwcp-gateb -f deploy/postgres/compose-gateb.yml config --quiet
```

secret 生成器只使用本地安全随机值，直写 O_EXCL/0600 文件，不输出值。PG 文件归 UID 999，API 副本归 UID 10001；不要认为 Compose 对 bind 文件的 uid/mode 字段会改变宿主权限。部署前核验所锁镜像 PostgreSQL UID；不符合时停止并修订映射，不用 chmod 644 解决。路径必须是全新的私有目录；生成失败后由操作者确认残留再清理，不覆盖旧秘密。

初始化脚本由 bootstrap 预装 pgcrypto，建立应用和迁移角色后收回 PUBLIC 权限并禁用 bootstrap 登录。应用角色不能拥有 DDL、CREATEDB、CREATEROLE、SUPERUSER。迁移工具最后将 schema_migrations 对应用收紧为只读。

先只启动独立 PG；API profile 不自动启动。迁移工具应运行在该 internal 网络中的一次性工具容器内，挂载同一只读源码及 migrator secret。不要为工具连接发布 PG 宿主端口或连接外部数据库。锁定依赖：`backend/requirements-postgres.lock`。

```bash
docker compose -p mwcp-gateb -f deploy/postgres/compose-gateb.yml up -d mwcp-gateb-pg
# 独立工具容器（UID999，只挂载migrator秘密；无宿主端口）：
docker compose -p mwcp-gateb -f deploy/postgres/compose-gateb.yml run --build --rm mwcp-gateb-migrate
# 迁移通过之后才启动候选 API：
docker compose -p mwcp-gateb -f deploy/postgres/compose-gateb.yml --profile api up -d mwcp-gateb-api
```

迁移工具必须先以当前源码构建完整镜像/工具环境并进行 import 冒烟。不要把本地演示 BFF 的临时 issuer 部署成生产登录。

## E1–E16 验收与证据（全部待 PG 实测）

| ID | 必须执行和留档 | 通过条件 |
|---|---|---|
| E1 | 空实验卷，0001→0002→0003→0004→0005，逐项校验版本和 SHA；重复 apply | 五条版本正确，第二轮无重复 DDL；缺版本/改 checksum 时 API 拒绝启动 |
| E2 | 停 API 后显式 `destroy-disposable-schema`；0005→0001；重新 apply | 只处理批准的实验 DB，版本表清空后重新得到相同结构；pgcrypto 为 bootstrap 安装的前置扩展，不删除 |
| E3 | 真实 PG 上的 API：同 key 同 payload 100 并发；异 payload 重放 | 仅一任务/审批；原 task_id 一致；异 payload=409 |
| E4 | 两个 API 进程共享实验 DB，同时取消/批准/状态转换 | 事务串行化，无丢更新，无终态复活 |
| E5 | API 资源变更/删除重建 A→B→A；任务和探针持旧 generation | 重启及并发之后仍拒绝旧授权/迟到提交 |
| E6 | 审批并发批准、消费与拒绝 | 一次性消费；拒绝任务不可领取；审计与状态同事务 |
| E7 | 过期审批/篡改 payload | 409/拒绝，不能执行；过期变化可恢复 |
| E8 | 租约失效/旧结果/重复 finish；新 API 进程重建 | 旧结果拒绝，合法幂等 replay；结果、尝试、产物和审计一致 |
| E9 | 以 mwcp_app 执行 perm-negative-tests.sql | 每条 CREATE TABLE/DROP TABLE/CREATE ROLE 单独捕获 42501；意外成功/25P02/别的错误均失败 |
| E10 | migrator DDL、app DML、版本表只读、容器秘密读取权限 | 全部符合最小权限，不靠 bootstrap 或 chmod 644 绕过 |
| E11 | 经 API 创建任务/会话/同步/上传；断开 DB；恢复；杀死并重建 API/PG | 断线返回 503，不确认未提交写；恢复后幂等重试；已确认记录、租约、产物字节和审计存在 |
| E12 | 一致性 pg_dump + 明确的角色恢复记录；新实验卷重建角色/restore | API 内容、行/对象、角色权限、检查点版本和内容 hash 一致；不向原卷 restore |
| E13 | 下述认证加密工具；正常恢复及密文/头/MAC/错误密钥负向 | 认证失败时不启动解密、不生成可恢复明文；正常结果内容一致 |
| E14 | 仅新实验 cgroup 内经批准 OOM/重启 | 不触及其他容器；记录 OOM 和 PG WAL 恢复、已提交记录；禁止宿主级内存耗尽 |
| E15 | 单用户 API 闭环 + 独立 benchmark 表 pgbench c8/j2/T300 | 记录 API/PG/静态服务总内存、CPU、磁盘/WAL峰值；不以单次 tps 宣称 1.5–2 GiB 目标已达成 |
| E16 | 127.0.0.1:8129/live；匿名业务 API；外部连接及容器路由 | live200，匿名401，PG无发布端口，API只回环，internal网络不能访问真实 Worker/探针/旧业务 |

E15 不使用旧方案 c20：PG max_connections=20，扣除保留连接、API和观测后不足以容纳20个普通客户端。使用专用实验表和 `pgbench -n -f deploy/postgres/pgbench.sql -c 8 -j 2 -T 300`；不能压测生产表/运行态检查点。所有结果附时间、命令退出码、commit、目标身份、测量范围和脱敏日志；未执行项标 NOT_RUN，不能生成全绿占位证据。

## 认证加密备份

独立加密/MAC 文件均为新生成的秘密；加密使用 AES-256-CBC + PBKDF2-SHA256(200000)，HMAC-SHA256 覆盖版本头、参数和全部密文。恢复先复制到私有临时目录并验签，再解密，避免验签后源文件被替换。密钥经匿名文件描述符，不进 argv/env。输出原子发布、不覆盖已有文件。

```bash
# 在已授权工具环境内，用受控连接配置；口令只经私有文件/进程读取。
set -o pipefail
PGPASSFILE=/run/secrets/backup-pgpass pg_dump -h mwcp-gateb-pg -U mwcp_app -Fc control_plane | python scripts/backup_crypto.py encrypt - /approved/backup.mwcp \
  --enc-key-file /run/secrets/backup-encryption --mac-key-file /run/secrets/backup-mac
python scripts/backup_crypto.py decrypt /approved/backup.mwcp /private/restore.dump \
  --enc-key-file /run/secrets/backup-encryption --mac-key-file /run/secrets/backup-mac
```

角色由冻结初始化脚本重建；如果导出 globals，禁止导出/留存口令哈希，或作为独立敏感备份同等加密和认证。`pg_restore --exit-on-error` 只对新的实验卷执行。保留期、异机备份和密钥恢复仍需运维方案；有加密文件不等于已完成备份恢复验收。

## 清理与生产阻断

先留存脱敏证据，再由操作者确认卷身份及销毁范围。只可对本次实验的 compose 项目执行 down；`down -v`、秘密目录销毁和逆迁移均为显式破坏操作，禁止自动收尾脚本或宽泛 docker prune/rm。

生产仍阻断于：真实 PG/API 事务和恢复验证、备份恢复、容量测量、生产身份与 session、TLS、真实 Worker/探针安全策略、美国宿主与旧业务隔离。模型推理、浏览器自动化和重型 Worker 不放主控；不引入 Redis/Loki/Prometheus/Kubernetes。
