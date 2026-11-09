# Frontend baseline — 2026-11-08 UTC

工作区 `/workspace` 初始为空，没有现成前端仓库、package.json 或 AGENTS.md。独立创建 `/workspace/mw-console`，没有访问 Mac 文件系统或旧业务。

输入：Drive Full Handoff v1.0.1 ZIP（45393 bytes），全部包内 manifest 校验通过；原 v0.4 ZIP（673692 bytes）。候选契约 SHA `18b42a97b3f975fcbe9a0326a1374d56fa547268e6fdefd18dc9cb529e8f7a25`，41 paths / 43 operations / 48 schemas。完整 PRD、两方角色提示词、路由与设计规格已读取。设计参考不是已接通生产的页面。

继承 v0.4 的 Spectra Motion 深色网格、节点角色颜色、模拟场景、控制台结构；转换为 React 组件和 CSS tokens。原 Motion HTML 在 docs/V2-MOTION-REFERENCE.html 留档。V1/Prism 移至 public/versions 以供 Vite 原样静态服务，逐字节相等，哈希见 docs/DESIGN-HASHES.json。没有修改历史 HTML。

技术：React 19 / TypeScript strict / Vite / Router / TanStack Query / openapi-typescript + openapi-fetch / MSW / Vitest / Playwright。图形为 SVG + CSS，没有 WebGL。依赖精确解析在 package-lock.json。

GLM 最终锁、真实新 API、GLM fixtures、BFF 身份实现均未提供；未伪造 CONTRACT-LOCK。候选响应 schema 是本地 fixture 的唯一字段来源。待修契约项见 CONTRACT-CHANGE-REQUEST.md。无远程运行与生产授权。

本地启动与验收命令见 README.md。
