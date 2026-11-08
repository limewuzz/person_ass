# CHANGES-SINCE-P0（GLM，2026-11-08 第二轮）

按评审 §F 要求区分四态。**Cherry Studio：零变更（未执行任何针对腾讯 Cherry 栈的命令）。生产系统：零变更。**

## 状态总表

| 项 | implemented locally | tested | deployed | approved |
|---|---|---|---|---|
| 仓库 mw-control-plane（git 8 commits） | ✅ | ✅ 33/33 pytest | ❌（仅 Mac 本地） | —（本地开发已授权） |
| P1-04 认证（Mock OIDC/JWT+中间件） | ✅ | ✅ 21 项（401×8/403×3/IDOR×2/日志/重放/nbf/me） | ❌ | 本地开发已授权；生产接入未申请 |
| P1-05 Registry（内存仓储+审计基线种子） | ✅ | ✅ 10 项契约测试 | ❌ | 本地开发已授权；**完整验收待 P1-03**（评审 §D） |
| /health/ready 503 语义修正 | ✅ | ✅（TestClient+真实 uvicorn） | ❌ | — |
| 回环绑定证明（lsof+LAN 双地址拒绝） | ✅ | ✅ | ❌ | — |
| PG 提案 **v2**（拓扑/回滚/备份 SOP 六项修订） | ✅（文档） | ⚠ YAML 语法本地校验过；`docker compose config` 需部署 Gate 执行 | ❌ | **未批准部署**（等待新一轮评审） |
| 3100 端口归属 | ✅ 调查完毕（rakazo-api 固定回环发布，10-22 起） | — | — | — |

## git 记录

```
<P0 后新增提交见 git log --oneline 输出，附录 A>
```

## 测试证据

- `backend/.venv/bin/python -m pytest tests/ backend/tests/` → **33 passed**（0.27s）
- 真实绑定：`lsof -iTCP:8123` → 仅 `127.0.0.1:8123 (LISTEN)`；`curl 192.168.1.2:8123` 与 `192.168.31.162:8123` 均连接拒绝
- 语义实测：live=200 / ready=503（deps: database=not_connected, auth=ok, probes=not_configured）/ nodes 无 token=401

## 契约偏差登记（待冻结时处理）

| ID | 偏差 | 处置建议 |
|---|---|---|
| C-1 | /health/ready 现实现 503+dependency_status；契约只声明 200 | 冻结时给契约补 503 响应（评审 §B 允许的权衡方向），tests/test_contracts.py 的占位断言同步更新 |

## 凭据与卫生

- 仓库内唯一「密钥样」字符串=测试用公开常量 `test-secret-only-for-local-tests`（仅签发本地 mock token，无任何真实系统关联）
- requirements.lock 23 行锁定全部传递依赖
- 全历史 secret 扫描（已知生产口令模式 / Google OAuth token 前缀 / OpenAI key 前缀 / PEM 私钥头）零命中

## 附录 A：git log --oneline + diff --stat（2026-11-08 第二轮末）

```
b4f8795 review: /health/ready 503 semantics, PG proposal v2, review docs, dep lock
4b1e9cb P1-05: resource registry (contract shapes, provenance, UNKNOWN/STALE decay) + tests
f7c5f46 P1-04: mock OIDC/JWT auth (fail-closed middleware, scope+IDOR guards, jti revocation) + tests
39988d0 P0/P1: P0 report + PG isolation PROPOSAL (not deployed, pending review)
bf6d924 P1-03(dev): minimal FastAPI health endpoints per contract, loopback-only dev
c276993 P1-02(prep): v0.4 candidate contracts + hash/count regression tests (31 paths/33 ops verified vs Drive original)
af815f0 P1-01: repo init with secret-exclusion .gitignore and boundary README

 backend/app.py                       |  97 ++++++++---
 backend/auth.py                      | 165 +++++++++++++++++++
 backend/deps.py                      |  12 ++
 backend/registry.py                  | 309 +++++++++++++++++++++++++++++++++++
 backend/requirements.lock            |  23 +++
 backend/requirements.txt             |   1 +
 backend/tests/conftest.py            |   4 +
 backend/tests/test_auth.py           | 143 ++++++++++++++++
 backend/tests/test_health.py         |  40 +++--
 backend/tests/test_registry.py       | 110 +++++++++++++
 deploy/postgres/PROPOSAL.md          | 121 ++++++++------
 deploy/postgres/compose.yml.proposal |  46 +++++-
 docs/CHANGES-SINCE-P0.md             |  60 +++++++
 docs/P1-04-AUTH-REVIEW.md            |  54 ++++++
 docs/P1-05-REGISTRY-REVIEW.md        |  58 +++++++
 15 files changed, 1162 insertions(+), 81 deletions(-)
```
