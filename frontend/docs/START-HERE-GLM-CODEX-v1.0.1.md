# MagicWorkshop｜完整本地 RC 交接 v1.0.1

**状态：本地开发计划与候选契约，不是生产部署许可。** 用户已要求 GLM 一次性完成后端、Codex 一次性完成前端。两个 Agent 独立仓库、共享唯一 OpenAPI 契约，代码证据交付至原私有 Google Drive「待完成」。

## 先读顺序

1. 两个 Agent 均完整读取 `MAGICWORKSHOP-FULL-PRD-v1.0-LOCAL.md`。
2. GLM 读取 `PROMPT-GLM-BACKEND-FULL-RC.md`：R10 基线、R11 两条负向先复现；全量实现后端模块、Registry generation、Mock 任务/审批/Worker 链，并发布 `CONTRACT-LOCK.json`。
3. Codex 读取 `PROMPT-CODEX-FRONTEND-FULL-RC.md`：全部 15 个功能页、四个详情模板、V2 首页与 V1/Prism 历史页面；对照候选契约生成 TypeScript SDK，完成 UI/Mock/E2E。
4. 候选契约 `MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml` 是 41 paths / 43 operations，当前 SHA-256 `18b42a97b3f975fcbe9a0326a1374d56fa547268e6fdefd18dc9cb529e8f7a25`。**只用于初始并行开发，不等于 GLM 的最终契约锁。** GLM 对外发布最终锁后，Codex 必须让生成 SDK 的哈希与它一致。不得互相静默修改 DTO。
5. 使用 `python validate_contract.py` 做基础合同静态校验；使用 `sha256sum -c HANDOFF-MANIFEST.sha256` 校验本包内容；对照 `HANDOFF-FILE-SIZES.csv` 检查原始字节。

## 单用户架构与安全界限

- 美国 6 核/约 11 GiB 候选唯一写主控，Mac mini 为本地 Worker 与只读备用入口；美国新控制平面**目标 1.5 GiB RAM，初期容量预留约 2 GiB**，未经压测不保证能耗；不引入不必要的 Redis/Prometheus/Loki/Kubernetes。
- **Cherry Studio 完全冻结**：不读取、访问、探测、编辑其任何代码、配置、数据库、凭据、会话、网络或 API，只有原有静态外链。旧 Rakazo、8765、Caddy/nginx、frp、cron、云端原业务也不触碰。
- **禁止**实际 PostgreSQL/Docker 运行、生产探针、凭据 A 轮换、生产 OAuth/第三方服务调用、生产部署或网络变更。只允许本地代码、纯合成 Mock、loopback 新开发服务、契约静态检查及脱敏证据上传。
- 每一个功能以 `IMPLEMENTED / TESTED / DEPLOYED / APPROVED` 四态报告，缺真实来源时必须显示 `MOCK`、`UNKNOWN` 或 `UNAVAILABLE`，不能假装上线。

## 本包内容

- `MAGICWORKSHOP-FULL-PRD-v1.0-LOCAL.md`：完整需求及验收（各后端域、UI、API、测试、Gate）。
- `PROMPT-GLM-BACKEND-FULL-RC.md`：可直接投喂 GLM 的完整后端工作指令。
- `PROMPT-CODEX-FRONTEND-FULL-RC.md`：可直接投喂 Codex 的完整前端工作指令。
- `MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml`：41/43 候选接口。
- `API-EXAMPLES-AND-CONTRACT-RULES.md`：模拟请求与响应示例。
- `CONTRACT-VALIDATION-REPORT.md`、`validate_contract.py`：离线契约核查。
- `HANDOFF-MANIFEST.sha256`（标准 sha256sum 格式）、`HANDOFF-FILE-SIZES.csv`：离线完整性检查。

## 原始项目资料

- 设计包 v0.4：https://drive.google.com/file/d/1LDv2VdadODjUguw4W0wvvdmru21HXBYT/view
- R10 后端源码：https://drive.google.com/file/d/1D-pCD-HjBVBdbgx656ZVv42YL7uzLyhm/view
- R11 Registry 负向：https://drive.google.com/file/d/1v8UgQ0BeCXi8m3r4gbGT2VtjzSX5-90J/view
- Drive「待完成」：https://drive.google.com/drive/folders/1x_RPC3RFCVTYAPEKbeFllEFMuRHzDS0b
