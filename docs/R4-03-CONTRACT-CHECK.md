# R4-03 · 契约自动化核查报告

生成：脚本化（`docs/r4_contract_check.py`，随源码包交付），非人工数路径。
时点：见 Git HEAD 元数据（R4-02 内 test-meta.txt 同源）。

## 1. 契约文件指纹

| 文件 | SHA-256 | 解析方式 |
|---|---|---|
| contracts/openapi.yaml | `8cee4d960834781cc217a2c99e256ece3dba43acc27fdbf1f76a7d0d3ef98425` | PyYAML safe_load |
| contracts/worker-protocol.schema.json | `a6d3c8b46173be068bbd218b719a46e189072323fedf10ec596a82cf07108d42` | json |
| contracts/capability.schema.json | `2df35f89aafb2379ea5bd0dd68be3a1a0261fb3585ad9611285995b4ccf0ce9c` | json |

## 2. 契约统计（脚本实测）

- paths = **31**；operations = **33**；操作级 x-phase = **33**（文件内字符串 34 次，差额来自 info.description 说明文字；脚本以操作级为准）
- 校验通过断言：与 v0.4 交接记录一致；tests/test_contracts.py 的哈希+计数回归同样覆盖

## 3. 实现 × 契约 路由差异表（脚本 diff FastAPI app.routes vs openapi paths）

| 状态 | 路径 | 说明 |
|---|---|---|
| IMPLEMENTED | 11 条：health/live+ready、me、nodes(+{id})、resources(+{id})、services、agents(+{id})、capabilities | 与契约模板完全一致（本轮脚本曾发现实现用 {node_id} 等命名与契约 {id} 不符——已修正代码对齐，属本报告的真实产出） |
| CONTRACT-ONLY（未实现，按期） | 20 条：work-items*/tasks*/approvals*/observations/audit/artifacts*/integrations/events/workers/* | 契约存在、backlog 未到（P1-07/08、P2/P3） |
| DEVIATION | /api/v1/health/ready：契约仅声明 200，实现返回 **503+dependency_status**（C-1 已登记；冻结时补 503 响应定义） | 已知偏差 |
| EXTRA（契约外路由） | /docs、/openapi.json、/redoc（FastAPI 自带文档面；生产暴露策略=R4-08 未决项，上公网前处置） | 非契约路径 |

## 4. Schema 校验

- 契约 JSON Schema（worker-protocol/capability）：`jsonschema` 库未入依赖——本轮**NOT RUN**（替代：文件哈希锁定 + 结构断言在 tests/test_contracts.py）；列入 P1-02 冻结前必做。

## 5. 复现命令

```bash
python docs/r4_contract_check.py   # 需 backend/.venv（fastapi/yaml）；输出本报告 §1-§3 的机器可读版
```
