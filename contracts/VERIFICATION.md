# 契约版本核验记录（2026-11-08）

针对 GPT-6 评审提出的「GLM 报 37 路径 vs v0.4 记录 31 路径/33 操作」疑问的核对结论：

| 项 | 值 |
|---|---|
| ZIP 内 openapi.yaml SHA-256 | `8cee4d960834781cc217a2c99e256ece3dba43acc27fdbf1f76a7d0d3ef98425` |
| Drive 独立副本 SHA-256（fileId 1K1lYcL__Glww1Sp1ULA8LeQyfdTA35Ab） | `8cee4d960834781cc217a2c99e256ece3dba43acc27fdbf1f76a7d0d3ef98425`（**完全一致，同一版本**） |
| 路径数（`awk '/^paths:/,/^components:/'` 计 `/^  \//`） | **31** |
| 操作数（同段计 `/^    (get|post|put|delete|patch):/`） | **33** |
| x-phase 标记数 | 34 |

**结论**：v0.4 记录（31 路径/33 操作）正确；GLM 首轮汇报中的「37」为口头误数（把结构索引里的 schema 段行误计入），未进入任何代码或契约。`tests/test_contracts.py` 将 31/33 固化为回归断言。

worker-protocol.schema.json SHA-256: `a6d3c8b46173be068bbd218b719a46e189072323fedf10ec596a82fc07108d42`
capability.schema.json SHA-256: `2df35f89aafb2379ea5bd0dd68be3a1a0261fb3585ad9611285995b4ccf0ce9c`

状态：CANDIDATE（评审冻结前不得作为生产 schema 执行）。
