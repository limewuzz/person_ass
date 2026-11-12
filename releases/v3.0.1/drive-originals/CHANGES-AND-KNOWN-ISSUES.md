# v3.0.1 — 变更与已知问题

基线：v3.0 = `c0cf4ed09f31532b6d5fb9486f5b29e574325776` / tree `72684d6234b11643dd1d891def989ff3e6b944a0`
交付：v3.0.1 = `2fa330f744b56d47169b34230a078adc6618b654` / tree `ced979dc77754eb75fb5e67ce2609e84d6ca1412`

契约未变：`3.0.0-fanout-local`，89 paths / 106 operations，
SHA-256 `28be05bbde88a55d3c97ce7ca1ebef70823be208d1ac216b36b70734f8625a6a`。
本次是两个实现层缺陷的修复，**不改契约、不改行为语义**。

## 一、已修复

### 1. UIBootstrap 报告的契约版本是过期的

`backend/queries.py` 把 `CONTRACT_VERSION` 写死为 `1.1.1-local-integrated`，而活动契约已是 `3.0.0-fanout-local`。这个值穿越 2.0 和 3.0 两次迁移都没动过，且 `backend/tests/test_queries_rc.py:51` **把错值写成了断言**，所以回归测试永远绿。

同时 `backend/clients_sync/service.py` 的 release manifest 报的是正确的 `3.0.0-fanout-local`，于是同一个服务里两个端点互相矛盾。

影响：界面顶部与 `/api/v1/ui/bootstrap` 来源展示区显示的契约版本是错的，违背 PRD「不得伪装真实状态」的同一条原则。

修复范围（4 个文件一起改，保持一致）：
- `backend/queries.py` — 常量改为 `3.0.0-fanout-local`
- `backend/tests/test_queries_rc.py` — 断言改为正确值
- `frontend/src/mocks/fixtures.ts` — Mock 数据同步
- `frontend/integration/corrected-fixtures/ui-bootstrap.json` — 契约校验基线同步

### 2. 新版 npm 会让 `npm ci` 后的构建静默失败

npm ≥ 11.19 默认拦截依赖的 postinstall 脚本。干净环境执行 `npm ci` 会成功，但 `esbuild` 的平台二进制没装上，之后 `vite build` 报错，且错误信息不指向根因。

CI 没抓到，因为它固定 Node 24，随附的 npm 版本早于该策略。

修复：`frontend/package.json` 增加
```json
"allowScripts": { "esbuild@0.28.2": true, "msw@2.15.0": true }
```
（注意：键含精确版本号，升级这两个包时需同步更新。）

## 二、已知问题（未修复，需要决策）

### A. fanout 分支在部署态不会自动推进

本地合成 worker（`frontend/integration/local_stack.py` 的 `synthetic_worker`）只领 `local.simulate` 任务，**不消费 outbox**。因此 `POST /api/v1/fanouts` 创建的计划，四个分支会一直停在 `QUEUED`，界面上看起来像卡死。

设计上这需要 Mac 中继进程消费：

```sh
python scripts/mw_outbox_dispatcher.py --url http://127.0.0.1:8127 \
  --worker-id <id> --node-id <node> \
  --token-file /run/secrets/mac-worker-jwt --mode SIMULATE --once
```

但 worker JWT 由受控发行方签发，本地 BFF 的密钥是进程内随机生成的（`local_stack.py:24` `secret = secrets.token_hex(32)`），外部无法自行签发。实测容器内也无法从 `/proc/<pid>/environ` 读取。

**建议**：给本地栈加一个显式的 evolver 开关（例如 `--auto-relay`），只为本地演示让 outbox 自动完成，生产路径不变。需你确认是否要改这一层。

### B. `FanoutCreate.targets` 的语义与命名不符

字段名叫 `targets`，实际传的是 **step_id**（`adr`/`issue`/`summary`/`archive` 等），不是目标平台名（`notion`/`github`/`drive`）。

契约里该字段只有 `pattern: ^[a-z]+`、长度限制，**没有 enum、没有 description**。`backend/fanout/service.py:139` 的校验是 `wanted <= {step_id}`。

实测踩坑：传 `["notion","github","implementation","wechat"]` 返回 `400 invalid_targets`，改为 `["adr","issue","implementation","progress"]` 才成功。前端之所以不暴露这个问题，是因为 UI 把 step_id 映射成了友好名（界面显示"Google Drive / Notion / Mac·提醒事项"，提交的是 step_id）。

**建议**：契约补 `description` 并按配方补 `enum`。这会改契约 SHA，连带 `CONTRACT-LOCK.json`、前端 SDK、fixtures，属于 breaking 流程，需要你批准后再动。

### C. 公网面没有速率限制

Basic Auth 是单一共享口令，无失败锁定、无 per-IP 限流。口令强度足够（24 位随机），但公网可达前提下建议叠加 fail2ban 或 nginx `limit_req`。

### D. 自签证书

无 CA 信任链。若提供域名，可切换 Let's Encrypt 自动签发，同时消除浏览器告警。

## 三、验证记录

| 检查 | 命令/来源 | 结果 |
|---|---|---|
| 后端全量 | `pytest tests backend/tests dbpg/tests frontend/integration/test_bff.py` | **276 passed**（14.77s） |
| 契约路由 | `node scripts/mw.mjs contract` | clean，`contract_only: []` |
| 前端构建 | `node scripts/mw.mjs build` | 1893 modules，658.88 kB JS / 208.16 kB gzip |
| 契约版本修复 | `GET /api/v1/ui/bootstrap` | `contract_version = 3.0.0-fanout-local` |
| fanout 创建 | `POST /api/v1/fanouts` | `201`，聚合审批 `PENDING` |
| fanout 审批 | `POST /api/v1/approvals/{id}/approve` | `200`，`CONSUMED` |
| 浏览器渲染 | Playwright，9 路由 | 全部 `200`，**0 JS 错误 / 0 失败请求** |
| 公网反代 | `https://<IP>/` | 无凭据 `401`，有凭据 `200` |
| SSE 穿透 | `/fanouts/{id}/stream` | `200 text/event-stream`，收到真实 `event: fanout` |
| 常驻内存 | `systemctl show -p MemoryCurrent` | 102.8 MiB |

证据文件见 `evidence/`：`pytest.txt`、`contract-route-check.txt`、`contract-sha256.txt`、`runtime-verification.json`。

## 四、状态声明

```
IMPLEMENTED = YES      两个缺陷已修并有回归
TESTED      = YES      后端 276 passed + 契约 + 构建 + 浏览器 + 反代
DEPLOYED    = YES      单机 Debian 12，systemd + nginx
APPROVED    = LOCAL_ONLY
PG_RUNTIME  = NOT_RUN
GATE_B/C/D/E = 未开
```

本轮未接触 Cherry Studio、Rakazo、8765、旧数据库、旧反代或任何生产节点，未轮换凭据，未向 GitHub 推送分支（仅在本地 `v3.0.1` 分支与 tag 上提交）。
