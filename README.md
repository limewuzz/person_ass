# mw-control-plane

MagicWorkshop 统一控制平面（美国主控 / Mac 温备入口 / UCloud 中继 / 腾讯不承载新主控）。

> **当前阶段：P1 受限开发**（2026-11-08 用户批准范围：本地仓库 + 回环 FastAPI 开发）。
> **未授权事项**：公网部署、域名/证书/反代、生产数据库创建（PG 方案先评审）、对现有生产业务的一切修改。

## 硬边界（违反任何一条 = 停止并上报）

1. **Cherry Studio 完全冻结**：不改程序/配置/模型/数据/账号/网络/部署，不做 Cherry 插件，不读其内部接口。
2. **现有生产不动**：Rakazo 调度（含 paper_ `15 1 * * *`）、Mac 8765 网关语义、生产数据库、nginx/Caddy 配置、全部定时任务。
3. **凭据零入库**：`.gitignore` 已硬排除；任何 secret 只存在于部署环境变量/钥匙串。
4. **事实分级**：VERIFIED_AT_AUDIT / LIVE / UNKNOWN / PLANNED / DEMO 严格区分（docs/P0 报告 §P0-05）。
5. 生产变更（建库/改网/重启/公网/调度）逐项申请，批准前只读。

## 仓库结构

```
contracts/        v0.4 候选契约（31 路径/33 操作，SHA 见 contracts/VERIFICATION.md）
backend/          FastAPI（开发期仅 127.0.0.1）
deploy/postgres/  独立 PG 提案（未部署，待复核）
docs/             P0 报告等工程文档
```

## 开发环境

```bash
cd backend
uv venv --python 3.12 && uv pip install -r requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple/
uv run pytest
uv run uvicorn app:app --host 127.0.0.1 --port 8123   # 仅回环
```

## 变更流程

- 契约（contracts/）改动 = PR + 评审 + 新 tag，禁止静默修改
- 每个提交对应 backlog 任务 ID（P1-xx）
- 旧功能零损失是每个 Gate 的硬标准（docs/GLM-P0-REPORT-2026-11-08.md §验收 Gate）
