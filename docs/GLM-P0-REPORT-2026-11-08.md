# GLM P0 只读环境核查报告（2026-11-08）

**执行者**：GLM（ZCode 会话）｜**证据时点**：2026-11-08 18:25–18:35 北京时间（10:25–10:35Z，美国机视角）｜**性质**：全程只读，未触碰任何生产配置/服务/数据（Cherry Studio 零接触）
**依据**：`MagicWorkshop-GLM-待完成-v0.4.zip`（38/38 SHA-256 校验通过）+ 本机实机审计包（同日早间）+ 本轮新鲜实测

---

## P0-01 服务/端口/属主/版本 对照表（三远程节点 + Mac）

结论：**与 11-08 早间审计一致，无服务增减异常**。差异/新证据见 ⚠ 标记。

### 美国服务器（6C/11G，Ubuntu 24.04.1，UTC）
- 监听（公网）：nginx 80/443(+QUIC)/2053、frps-assistant 7100 + **`*:18085`/`*:18086`（⚠ 审计写"仅容器网段"——实为全接口绑定，但 ufw `DENY Anywhere` + 仅 `ALLOW 172.16.0.0/12`，公网实际不可达，结论修正为「ufw 层隔离」）**、sshd 22、BT-Panel 23793、FTP 系 20/21/888/39000-40000、sing-box 8443
- 监听（回环）：docker-proxy 5173/6081/6082/7681/7682/7684/8317/**3100（审计后新出现的 docker 端口，映射身份待 P1 确认）**/58630、node 38527、socat 54545、assistant 8899、api_coco 3010（0.0.0.0 但 ufw 未放行→仅经 nginx）
- 容器：13 个 Up（rakazo 5 + cliproxy + chromium×2 + webcli×4 + kimi-web-probe），镜像/版本与审计一致（postgres:**16**、cli-proxy-api v7.2.94、rakazo app:edge）
- 运行时：Python 3.12.3 ✓ / Node v22.23.2 ✓ / 宿主无 psql 客户端（经 docker exec）
- ⚠ **ufw 注释解答审计 U3**：8443+443/udp = sing-box shadowsocks（net_pr）、23793 = 宝塔

### UCloud（2C/1.9G，Ubuntu 22.04.4）
- 监听与审计完全一致：caddy 80/443/2080/2019、frps 7000（回环 18080-18084 五隧道**全部在册**）、rustdesk 21115-21119、sshd
- 内存余量 1.5Gi available

### 腾讯云（2C/1.9G，Ubuntu 26.04）
- 监听与审计一致：nginx 80/443/7443/8080/18443、CherryStudio 0.0.0.0:23333、cherry-web 7180 回环
- ⚠ **Mac 反向隧道 18085 当前绑定成功**（sshd-session 双栈监听，即 cherry-relay 此刻健康——审计记录的端口占用病灶是间歇性而非持续）
- 服务状态复核：meshcentral=enabled(dead) ⚠ 重启自启风险仍在；meshport80/mwrelay/cherry-qr-rotate=disabled；cherry-pairing-watch/cherry-web=enabled+running

### Mac mini
- 11 个 launchd 服务全部运行中（PID 与早间审计相同=未重启）；cron 11 条不变；assistant.db 持续在写（1,847,296B，较审计 +约 5KB）；8765/8799/7100/8080/3080/8090 回环监听确认

## P0-02 网络路由实测矩阵（本轮新鲜证据）

| 路由 | 方法 | 结果 | 对照基线 |
|---|---|---|---|
| Mac→US 直连 | curl magicworkshop.fun | ❌ 000/8s 超时 | 一致（家宽屏蔽持续） |
| Mac→US 经 mihomo（域名→MW-US） | curl -x 7890 | ✅ 200/**0.67s** | 一致（本轮 SSH 亦全程走此路，5 次会话稳定） |
| US→Mac（DDNS https） | curl magicworkshop.site | ❌ 000/0.3s | 一致（v6-only + 无出站 v6） |
| **腾讯→US** | curl https + nc 443 | ✅ **200/0.75s + TCP open** | ⚠ **重大变化**：10-21 基线与审计引述的「互不可达」已失效（审计期间 agent 用腾讯跳板 SSH 美国成功亦是旁证） |
| **US→腾讯** | nc 443 + curl https | ⚠ **TCP open 但 TLS 失败**（000/0.97s） | 半通：L4 可达、L7 TLS 断（方向性差异，疑出境 SNI 干扰） |
| UCloud→US https | curl 回源 | ✅ 200 但 **6.78s**（早间 0.76s） | ⚠ **异常样本记录**：单次劣化观测，与 mofang 502（Caddy 回源 DNS 超时日志实锤）是否同根因**未证实**，需多点采样后再定 |
| UCloud→US 7100 | nc | ✅ open | 一致（助手隧道健康） |

**设计含义（供 ADR 修订）**：① 美国主控对 Mac 只能靠 Mac 主动外联（轮询/长连接经 mihomo 域名路由或 UCloud 中继），不可反向直连——与 v0.4 假设一致；② 腾讯→美国单向可达意味着腾讯侧未来可做只读探针上报，但 US→腾讯推送不可依赖（TLS 断）；③ UCloud→美国链路当天在 0.7–6.8s 间波动，任何经 UCloud 回源的路径需设 ≥10s 超时+重试。

## P0-03 新部署资源预算（美国机）

- **内存**：总 11.68GiB，已用约 5.8GiB，**available 5.9GiB**。容器侧 top：grok 镜像 1.28GiB、rakazo-api 703MiB、worker 636MiB、chatgpt 636MiB。**新控制面预算建议**：FastAPI ≤256MiB + 新 PG16 容器 ≤512MiB + 预留缓冲 ≈ 1GiB，占比 <17%，可行。
- **磁盘**：/ 97G 用 38G（60G free）。Docker 可回收：build cache 946MB + 未用卷 1.97GB（不动，仅记录）。
- **PG≥15 需求验证**：rakazo 已运行 postgres:16（digest 锁定）→ **独立新容器方案可行**（新库、新卷、新 role，绝不复用 rakazo 实例——符合 SQL 文件头要求）。
- **可用端口方案**：新服务一律绑 127.0.0.1，经现有 nginx 443/2053 vhost 加 location 或新 server 块反代——**零新增公网端口**；回环空闲端口充足（避开已列清单）。
- **目录**：`/root/magicworkshop/` 下与 api_coco/assistant 平级新建（如 `control-plane/`），不触碰既有目录。

## P0-04 备份与 secret 暴露（无值清单）

- **备份实物复核**：UCloud Caddyfile .bak ×8 + certs/ + apk 历史版本 ×3 ✓ 存在；美国 nginx-config-backups/、Mac cherrystudio-20261107 备份 ✓（审计记录）。**Rakazo postgres、assistant.db、全部代码仍无自动备份**（审计结论维持，P1 需补）。
- **secret 暴露面**（沿用审计 09 §5，本轮无新增值）：EXECUTOR_API_KEY ×5 处（含 Rakazo 提示词 ×2）、STATE.md 明文凭据表、dsh plist 明文 key、password.txt、Android keystore 密码——**P1-01 git init 前必须先按 v0.4 要求做排除清单**。
- **新证据**：美国机 ufw 注释本身不含 secret；rakazo compose 的 POSTGRES_PASSWORD 走 .env 注入（本次读取全程屏蔽）。

## P0-05 v0.4 设计 × 现状 契约差异表

| # | v0.4 假设/引用 | 现状证据 | 判定 |
|---|---|---|---|
| C1 | 「美国↔腾讯断链」（01 文档） | 腾讯→US 200/0.75s；US→腾讯 TCP open/TLS 断（本轮） | **STALE-需修订**：**仅腾讯→美国单向 HTTPS 可达**（单次时点样本）；反向 TLS 失败=不可依赖双向。不得表述为「链路恢复」 |
| C2 | 「US→Mac 不通」 | 000/0.3s（本轮） | VERIFIED 维持 |
| C3 | paper_ `15 1 * * *` 01:15 | routines 表实时读取：`{"15 1 * * *"}` Asia/Shanghai active（18:32） | VERIFIED（U08 关闭） |
| C4 | 三 bot 调度 | Chief `30 9` ✓ 复盘官 `30 21` ✓ + **新发现第 4 个活跃例行「每周四周报」`0 12 * * 4`**（审计未记录，Workflows 页数据源需纳入） | VERIFIED + 补充 |
| C5 | 审计 #17「Google 贡献为零」不实 | 本会话用 Drive OAuth 完成上传+下载回环（146,095B SHA-256 一致） | **v0.4 修正成立**；审计 11-ARCHITECTURE-FACTS #17 需同步修订 |
| C6 | Mac 网关 model 不选路/伪流 | 审计 evidence/03 api.py:167 + 本轮服务存活 | VERIFIED（新平台不得改变其语义） |
| C7 | 新 API `/api/v1/*`（**31 路径 / 33 操作**——与 v0.4 记录一致；首轮汇报口头误数为 37，已用 `awk '/^paths:/,/^components:/'` 精确重数并经 Drive 原件 SHA-256 `8cee4d96…` 与 ZIP 副本一致性确认版本相同） | 全部为**新增命名空间**，与现有任何旧 API（portal/control-api/8765/assistant/rakazo/cliproxy/quota-relay）**零路径冲突**（对照审计 api-registry.json） | VERIFIED 无冲突 |
| C8 | SQL 要求 PG≥15 隔离库 | postgres:16 镜像在库、60G 磁盘、5.9Gi 内存 | VERIFIED 可行 |
| C9 | UCloud 仅中继不改 | frps 五隧道在册、Caddy 7 站点运行中（本轮 ss/journal） | VERIFIED 维持 |
| C10 | 18085/18086 容器网段隔离 | `*:` 绑定 + ufw DENY（仅 172.16.0.0/12 放行 18085） | **已按评审补全四层证据（18:50 复核）**：① frps-assistant 为宿主进程（非容器端口发布，不构成 Docker 绕过面）；② docker inspect 全量：10 容器端口绑定**全部 127.0.0.1**、DNAT 规则目标均为 `-d 127.0.0.1/32`；③ ufw 默认 deny incoming+routed，宿主无全局 IPv6 且 ip6tables 对 18085/18086 显式 DROP；④ **双外部视点实测**（UCloud+腾讯 nc）：18085/18086/3010 全 CLOSED/FILTERED，23793/8443 OPEN 与 ufw ALLOW 互证。**判定：隔离有效** |
| C11 | Cherry 完全冻结 | 本轮对腾讯仅执行 ss/systemctl is-enabled/curl 只读命令，零写入零重启 | VERIFIED 遵守 |
| C12 | US 新端口 3100（docker-proxy） | 审计后出现，映射目标未知 | **UNKNOWN→P1 首查项** |

## 拟创建的新仓库与模块清单（待 P0-06 批准后执行）

```
~/develop/mw-control-plane/          # 新 git 仓库（P1-01；先写 .gitignore 排除 .env/*/secrets/*，再 git init）
├── contracts/        # 从 v0.4 冻结副本起步（openapi.yaml + 2 schema），P1-02 冻结打 tag
├── db/               # Alembic 迁移（001_control_plane.sql 转译）+ 回滚脚本
├── backend/          # FastAPI（参考 reference-backend/ 桩重写，非部署桩本身）
├── adapters/         # 旧系统只读适配器（8765/control-api/portal status/rakazo 只读）
├── frontend/         # Design System + 15 页（V2 Spectra Motion 基线，V1/Prism 原件入 versions/）
└── workers/mac/      # Mac Worker（P1-07，心跳+claim，无生产动作）
```
美国机部署目录：`/root/magicworkshop/control-plane/`（独立、可整体回滚删除）。

## PR/Commit 规划（P1 对齐 backlog）

| PR | 内容 | 对应任务 |
|---|---|---|
| #1 | chore: repo init + .gitignore（secret 排除清单）+ docs 链接 | P1-01 |
| #2 | feat(contracts): v0.4 契约入库 + lint 冻结 tag v0.4.0 | P1-02 |
| #3 | feat(db): alembic 初始迁移 + up/down/restore 测试 | P1-03 |
| #4 | feat(auth): bearer/OIDC 骨架 + 401/403/IDOR 测试 | P1-04 |
| #5 | feat(registry): nodes/resources/services/agents + 契约测试 | P1-05 |
| #6 | feat(probes): US/Rakazo/Mac 只读探针（source/ttl 字段） | P1-06 |
| #7 | feat(workers): 心跳协议实现 + 吊销测试 | P1-07 |
| #8 | feat(tasks-api): 只读查询/过滤/分页 | P1-08 |
| #9 | feat(frontend): shell + design tokens + 4 断点测试 | P1-09 |
| #10–12 | 页面三批（Dashboard/Nodes/Services/Agents → Tasks/Approvals/Observability + 4 详情） | P1-10/11 |
| #13 | feat(frontend): Spectra 首页集成 + 历史原件 SHA 校验 | P1-12 |
| #14 | test: P1 回归矩阵 + 截图证据 | P1-13 |

## 分期验收点（建议 Gate）

- **G-P0**（本报告）：用户批准 P0-06 范围（建仓库、staging DB 容器、回环开发服务）
- **G-P1**：旧功能零损失清单全绿（旧入口可登录/调用、paper_ 等例行不重复、8765 语义不变）+ 91 个旧测试仍绿 + 新契约测试通过
- **G-P2**：幂等 100 并发测试、审批 token 一次性/时效测试、断线对账演练、美国主控宕机不双写演练
- **G-P3**：逐项 OAuth scope 实测矩阵

## P0-06 审批请求（等待用户明确同意，未批不动生产）

1. 创建 `~/develop/mw-control-plane` git 仓库（纯本地）
2. 美国机 `/root/magicworkshop/control-plane/` 目录 + **独立** postgres:16 容器（仅容器网，不发布端口，不复用 rakazo 库）
3. 开发期 FastAPI 仅绑 127.0.0.1（暂不做公网反代/域名/证书——那是独立审批项）
4. （可选）将本报告上传 Drive「待完成」供 GPT-6 复核
