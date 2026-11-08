# CHANGES-R3（GLM，2026-11-08 第三轮 · 响应第二轮评审）

**Cherry Studio：零变更。生产系统：零变更。美国容器/数据库：未启动。凭据：未轮换（计划待批）。**

## 状态总表（评审 R2 §5 五项逐一对应）

| 评审要求 | 状态 | 证据 |
|---|---|---|
| 1. P1-06 只读探针（Mock/快照） | ✅ implemented locally + tested（8 测试） | backend/probes.py + tests/test_probes.py；docs/P1-06-PROBE-REVIEW.md |
| 2a. P1-04 补测：Service 越权/边界/fail-closed | ✅ 4 新测试 | test_auth_v2.py：service 声称 admin:read 被强制剥离；worker path≠subject→403；validator=None→503（真实中间件） |
| 2b. P1-05 补：observed/received 区分 | ✅ 代码+测试 | 快照 observed_at=证据时间、received_at=装载时刻，断言可区分 |
| 3. PG v3（secrets/最小权限/恢复/预算） | ✅ 文档+配置（NOT DEPLOYED） | compose-v3.yml.proposal + init-roles.sql + PROPOSAL.md v3（BLOCK-01~06 逐项对照表） |
| 4. 口令事件：无秘密值说明+轮换计划 | ✅ 已提交待批 | docs/SEC-INCIDENT-2026-11-08.md（R1-R8 步骤；未批不动） |
| 5. 材料上传 Drive+提交 SHA | ✅ 本文件随附 | 见「测试与提交」节 |

## 命名澄清（评审 §3）

Mock 认证在代码与全部文档中统一称 **「Mock JWT 验证」**（非生产 OIDC）。真实 issuer/JWKS/非对称密钥=未来独立验收。

## 测试与提交

- `pytest tests/` → **43 passed**（0 失败）：契约 3 + health 5 + auth 16 + auth_v2 4 + registry 11 + probes 8 之前为 33，本轮 +10）
- 提交（SHA 见上传时的 git log 附言）；全历史 secret 扫描零命中；`.git` 对象库已 reflog-expire + gc --prune=now 物理清除（事件报告 §2）

## 修正记录（本轮自己抓到的）

- 漏实现契约 `/api/v1/resources/{id}`（31 路径之一）——补上并带对象级守卫；ThreadingHTTPServer 修正 Mock 目标串行阻塞。

## 未决项（等用户/评审）

1. 凭据 A 轮换计划批准（SEC-INCIDENT §4）
2. PG v3 复核 → 部署 Gate 批准
3. P1-06 生产目标清单（含 UCloud/US 只读探测对象）= 新审批
4. `/docs`、OpenAPI 端点的生产暴露策略（上公网前确认）
