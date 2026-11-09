# Joint Local RC evidence index

当前契约：1.1.1-local-integrated，41 paths / 43 operations，SHA e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa。原GLM ZIP/YAML及V1/Prism字节保留。

最终双仓库HEAD、每步退出码和联合结论只由evidence/release/integrated-release.json给出。脚本scripts/verify-integrated-release.mjs要求两个源码目录均clean，依次验证后端正反收集顺序、实际43操作schema、额外35项独立审查、BFF、前端、MSW和真实loopback浏览器测试。它不会把MSW成功当作实际API联调成功。

| 证据 | 内容 |
|---|---|
| 后端源码ZIP | 独立修复分支，原GLM基线可对照，锁、迁移静态材料、完整测试和修复差异 |
| 前端源码ZIP | 22模板、生成SDK、同源session BFF、CSRF、SSE、Mock和联调工具 |
| 契约/后端测试ZIP | 当前/原始锁、固定输入、双顺序JUnit、43路由/操作覆盖、35项审查、回归迁移说明 |
| Mock E2E ZIP | 8浏览器用例、90张四尺寸截图、基本WCAG与reduced motion、类型/lint/构建日志 |
| 实际联调ZIP | 7浏览器用例、全部22模板四尺寸截图、审批/Worker/结果/对账、断网恢复、HTTP交换及本地RSS观测 |
| Manifest | 上传物SHA/bytes；私有Drive逐件下载回读 |

每页四态和API映射见PAGE-STATUS.md。数据都为合成/历史目录，外部集成UNAVAILABLE；只对本地控制账本执行模拟。PG适配器仍未完成、PG/Docker运行与真实探针/OIDC/部署均未运行。不得把本地RC称作production-ready。
