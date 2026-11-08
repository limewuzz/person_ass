# BASELINE-FACTS（RC 轮，2026-11-09）

## 一、本轮本地可验证事实（全部命令级）

| # | 事实 | 证据 |
|---|---|---|
| F1 | R10 基线 HEAD `7fa9f30` clean，109/109 绿 | 本轮 BASELINE 阶段实跑 |
| F2 | R11 两项负向在 R10 HEAD **2/2 复现失败** | `/tmp` JUnit 已并入 R11-03 流程，`test_r11_gpt6_repro.py` 前置复现记录 |
| F3 | 契约 1.1 = 41 路径/43 操作；对 v0.4 31 路径**逐字节零漂移**（脚本 diff）+10 新只读；Resource 增可选 generation/lifecycle_state | `contracts/CONTRACT-LOCK.json`（SHA `18b42a97…`）+ `tests/test_contracts.py` |
| F4 | 路由 diff：**41/41 全部 IMPLEMENTED**，0 contract-only，0 extra（除文档面） | `docs/r4_contract_check.py`（脚本化） |
| F5 | 全量测试 **156/156**（JUnit）双收集顺序一致；含外部 R11 副本 158/158 | RC-02 zip 内 junit.xml |
| F6 | loopback 冒烟 8127：live 200/ready 503(诚实)/bootstrap 200/workflows 200/任务创建 201；LAN 地址拒绝 | 本轮 smoke 命令输出 |
| F7 | RSS ≈ **51.7MB**（uvicorn 全模块装配后）——1.5GiB 预算余量充足（设计目标，非压测承诺） | smoke 期间 `ps -o rss` |
| F8 | PG 侧仅静态：DDL+仓储蓝本，`PgTaskRepo.* → NotImplementedError` | `tests/test_dbpg_static.py` |

## 二、Drive 历史来源（引用，非本轮产生）

- R10 评审/R11 指令与负向证据（本轮下载核验 SHA 后使用）
- FULL-HANDOFF v1.0.1 ZIP + 1.1 OpenAPI 基线（交接包 manifest 校验通过）

## 三、仍未测（NOT RUN / UNKNOWN）

- PG 运行期全套（首启/权限/迁移/恢复/pgbench/OOM/回环）——**未获批，代码仅静态**
- 真实探针（生产白名单仍为空集——by design）
- 生产 OIDC/JTI 持久化/公网反代/凭据 A 轮换（OPEN）
- DNS rebinding TOCTOU 根除（缓解维持）
- 1.5GiB 常驻目标仅为设计预算：未做多日观察、未在美国机测量
