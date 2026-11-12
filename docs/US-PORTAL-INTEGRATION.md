# magicworkshop.fun — 美国机统一入口候选

目标域名 magicworkshop.fun，公开DNS解析为50.114.172.213。当前目标由原单机v3.0.1试验环境改为美国机，但本次构建工具不连接SSH、不部署或改写现网。保留既有业务；GLM原有部署分工沿用，最终切换须完成实际路径、身份和回滚核验。

## 已观察的现网与差异

只读访问确认根首页是AmazingWork，并不是MagicWorkshop控制平面。页面采用访问码表单，静态前端使用/v1/personal/verify、/v1/personal/status等既有模型API；/agent是独立的官网与CLI入口聚合页，另有/models、/usage/。未登录账号、未发起模型请求、未打开官网镜像/终端/下载/额度探测、未读取服务器上的密钥或旧业务配置。

对/api/v1/me的匿名GET返回的是SPA HTML 200，并非MagicWorkshop身份JSON。不能把这个200当作会话有效，也不能将现有访问码直接当作新控制平面的JWT、SSH凭据或生产认证。

2026-11-12 再次只读核实：`/`、`/workshop/`、`/workshop/build-meta.json`、`/api/v1/me`及健康路径均返回同一份531字节AmazingWork HTML（SHA-256 `de53e78f95e00cc77ca948bceca90eecea1316a6ea03beae89d9905c954a1c35`）。这是已观察到的旧SPA兜底，不能证明新前端或API已接入；也不能单凭外部响应确定服务器内有没有新文件或进程。PR #9 的归档恢复和CI通过本身不会改变现网路由。

`docs/V3.0.1-*.md` 是历史入口，不是美国机部署手册。六份Drive原文完整保存在 `releases/v3.0.1/drive-originals/`，由CI检查字节哈希。其公开模拟身份、固定改写Origin、自签证书和oneshot示例不能替代本节的身份与回滚Gate。

## 可预览的重构

- frontend/portal是独立静态入口，沿用已接受的浅色纸张与绿色风格。提供四类工作入口、搜索、草稿交接和已有工具静态链接；不后台请求模型、旧系统或控制平面数据。
- /提供新统一首页；新工作坊完整应用放/workshop/，避免其/models等页面与旧站同名路径冲突。
- /chat/保留旧聊天入口；/agent、/models、/usage/、/v1/、/assets/均由原有处理链继续服务。实际Nginx现有fallback和/chat/映射需部署者检查确认；不是已经切换的事实。
- 草稿只在同源sessionStorage保存，30分钟过期。正文不进URL、日志或公共页面。跳入工作坊后只预填并选择配方，不自动创建任务；待用户检查、授权后才提交。
- 新工作坊session候选只读启动，继续使用HttpOnly Cookie、服务端身份验证和既有CSRF/Origin边界；无公共模拟会话发行器。

UI外链不预取、不代理或iframe旧业务。Cherry/Rakazo/8765以及既有模型网关的代码、认证、会话与服务配置不改。

## 本地与候选构建

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
# http://127.0.0.1:5173/portal/ ; 同源草稿可转入 /workbench/fanout
npm run build:portal --prefix frontend
node scripts/mw.mjs build-us --preview  # 未提交源码，只供本地设计核对
node scripts/mw.mjs build-us            # 干净源码的静态美国机候选
```

由GLM完成已授权的静态/身份路由映射后，用只读检查确认没有把旧HTML兜底当成成功：

```sh
python3 scripts/check_us_deployment.py --url https://magicworkshop.fun --expected-commit "$(git rev-parse HEAD)"
```

该命令只发匿名GET，不携带Cookie或认证、不跟随重定向、不访问Worker、本地身份发行器或旧模型API。它验证两套资源前缀及类型、JSON构建身份/契约/只读模式，以及匿名`/api/v1/me`的401 JSON；HTML 200、错误构建或隐式admin均返回非零状态。退出0只说明本次只读候选的外部冒烟通过，**不代表生产已验收**；真实会话、CSRF/Worker、PG与容量仍须独立验收。构建与下载的候选提交必须和`--expected-commit`一致；优先使用合并后CI产物或在最终提交上重建。

候选位于release/us-candidate/<commit>/，含portal/、workshop/、CANDIDATE-MANIFEST.json与SHA256SUMS.txt。主页资产单独使用/portal-assets/，不覆盖原/assets/；工作坊资产使用/workshop/assets/。候选清楚标记未部署、只读、认证运行期未核验、PG未运行；不包含凭据或生产后端替代品。

v3.0.1的五文件补丁可还原出声明tree ced979dc77754eb75fb5e67ce2609e84d6ca1412，其中Bootstrap版本修复有效。本分支吸收该修复，并改为从唯一契约读取版本；npm allowScripts作为明确脚本授权保留，不声称它能解释所有环境的构建失败。活动OpenAPI的字节、89/106与SHA不变。

## 美国机切换检查表

1. 部署者只读检查magicworkshop.fun所属vhost、静态目录、现有旧入口fallback和新控制平面专属服务；记录当前资产清单与版本，不读取其他业务秘密。
2. 备份该站原首页/自身配置和旧静态发布目标，保留其/assets/以及旧应用入口，准备仅恢复所改几处位置的回滚。
3. 准备真正的新控制平面会话BFF，验证真实域名Origin，不固定重写Origin；匿名身份接口401、有效Cookie200、过期/伪造Cookie拒绝、CSRF与Worker隔离通过。不得用公开/local/session或固定admin bearer替代。
4. 阅读现有/路径fallback后，为新主页增加精确location = /，为/portal-assets/、/workshop/添加独立映射；不覆盖服务器全局root、原/api或/v1代理，不删除其他enabled站点，不更改DNS/凭据或业务端口。
   构建元数据和`/workshop/assets/`按模板单独`try_files ... =404`；只有实际客户端页面深链可以回退到工作坊index。缺少JSON或JS不能返回SPA HTML200。
5. 静态候选SHA、build-meta、登录后进入与深链刷新、新旧入口、SSE和用户意图不重复提交全部通过后，才由部署者执行最小切换与普通配置校验/reload；保留原发布目录。
6. 失败恢复上一静态目标与仅改动的配置，重新核验旧入口。PG迁移、持久化、备份恢复、真实Worker/连接器和资源预算另行验收，不把本次静态界面构建当作这些Gate已经满足。

此目录提供精确的location候选模板，不提供猜测的生产身份、上游地址、密码或一键覆盖现网脚本。当前云工作区未配置服务器部署Secrets。网站账号可用于已确认的网页登录用途，不能替代SSH授权与传输配置。
