# GLM RC independent review — resolved locally

原始审查保留于docs/baseline/GLM-RC-INDEPENDENT-REVIEW.md，原Drive源码包不变。用户随后授权在独立副本修复，后端为mw-control-plane-integrated，原始包对应f13d6e5。

原始156回归通过，但追加35项运行期检查24失败，另一个最终revision读取窗口能复现owner已变却提交旧healthy。修复后的响应、状态码、完整HTTP幂等、审批/Worker/产物与资源提交协议已实现；新增43操作schema校验及并发/IDOR/过期/参数绑定等测试。回归迁移的具体假设改变见后端docs/TEST-MIGRATIONS.md，原始失败原件未覆写。

原SHA 18b42a97…f7a25 → 兼容修订SHA e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa；仍41/43，新增可选参数上下文及诚实503语义。两端同一YAML，BFF不做字段别名转换。

当前验收以evidence/release/integrated-release.json为准，它由干净的双仓库HEAD启动完整验证、实际loopback API、共享锁/SDK检查后生成。历史失败不等于当前失败，最终通过也不代表生产部署、PG或真实身份接入通过。
