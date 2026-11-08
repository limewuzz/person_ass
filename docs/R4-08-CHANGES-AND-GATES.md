# R4-08 · 变更记录与门槛（本轮）

## 1. Git 证据基线（见 R4-02 内 test-meta.txt 同源输出）

- HEAD：见 meta 文件（本文件生成时写入，带时区）
- `git status --porcelain=v1`：clean（工作树与 HEAD 一致，无混合态）
- `git log -n 12 --oneline` / `git diff --check`：见 meta 文件原始输出

## 2. 测试数量矛盾的解释（R4-A3，不复述只证因）

| 历史口头数 | 真实口径 | 命令 |
|---|---|---|
| 33 | 仓库级（契约 3 + 后端 30），R2 末 | `backend/.venv/bin/python -m pytest tests/ backend/tests/`（仓库根执行） |
| 43 | **仅后端目录**（cwd=backend，`pytest tests/` 不含仓库级契约 3），R3 中段 | `cd backend && pytest tests/` |
| 46 | 仓库级（3+43），R3 末 | 同 33 行命令 |
| **53（本轮）** | 仓库级：契约 3 + 后端 50（新增 SSRF×6+redirect+batch +1 resources 详情修正） | 同上，JUnit 证据见 R4-02 |

根因：跨目录执行时 `tests/` 相对路径解析到不同集合——非测试丢失。本轮起固定唯一命令（R4-02 记录），JUnit XML 为唯一权威计数。

## 3. 本轮变更（四态）

| 项 | implemented locally | tested | deployed | approved |
|---|---|---|---|---|
| 探针 SSRF 三层校验+生产空白名单 | ✅ | ✅ 6 负向测试 | ❌ | 本地已授权 |
| 3xx 不跟随+redirect 态 | ✅ | ✅ | ❌ | 同上 |
| run_batch 并发上限 | ✅ | ✅ | ❌ | 同上 |
| 契约对齐：详情路径 {id}（原 {node_id} 等） | ✅ | ✅ 53/53 | ❌ | 同上（R4-03 记录真实差异发现） |
| PG v4（可执行角色初始化/Dockerfile/entrypoint/权限矩阵） | ✅ 静态 | ⚠ 仅 YAML lint + 人工审查 | ❌ | **未申请部署** |
| 契约核查脚本 r4_contract_check.py | ✅ | ✅ exit 0 | — | — |
| 安全事件更新/探针审查/本文件 | ✅ 文档 | — | — | 轮换待批 |

## 4. 逐条 Gate 与下一步申请

| Gate | 当前状态 | 阻断 | 下一步 |
|---|---|---|---|
| 凭据 A 轮换 | **待用户批准**（R4-06 §3 矩阵） | AI 会话副本不可清除 | 用户点头后按 R3-R8 执行 |
| PG 部署 | 未申请 | v4 静态评审 → 权限反例 NOT RUN → pgbench 未压测 → 回环可达未实测 | GPT-6 复核 R4-04/05 → 批准隔离环境演练 → 再申请部署 Gate |
| P1-06 生产探针 | 未申请 | 生产白名单为空（by design） | 提交目标清单（UCloud/US 只读端点+频次）单独审批 |
| P1-07 Worker / P1-08 Tasks | 未开始 | backlog 顺序 | P1-03 数据库落地后 |
| /docs 生产暴露策略 | 未决 | — | 上公网前禁用或鉴权（openapi.json 含全部路由面） |

## 5. 本轮零接触重申

Cherry Studio / Rakazo 调度 / 8765 / 生产库 / nginx/Caddy / 美国容器：**零变更零调用**。探针仅打本地 Mock 端口。
