# V3 一点多触发：实施与验收边界

V2.0.1 `c17b64b` 为冻结祖先，新增配方、HMAC 入口、Outbox 独立租约、Mac 中继和 `/workbench/fanout`。22 种原页面/模板与 V1/Prism 保留；四套新配方、目标选择、合并审批、队列回执及签名调用说明新增到原前台，不重写应用。

## 一次入站与四套配方

`POST /api/v1/fanouts` 是标准新入口。旧 `POST /api/v1/work-items/{id}/dispatch` 可显式提交 FanoutCreate 复用已有项（202），原 local.simulate 请求仍兼容。会话 `POST /api/v1/conversations/{id}/messages` 可加 `fanout: FanoutCreate`，记录一条消息并复用/关联一个工作项；不得与 spawn_capability 混用。无关键词自动执行或隐式读 Cherry 会话。

配置 `backend/fanout/recipes.json` 为唯一配方源，生成命令同步到前端 Mock，不允许前端自行降级风险。加载时拒绝未知目的端、重复 step、循环/前向依赖及算力/GitHub/实现步骤降为 LOW。

| 配方 | 分支与依赖 | 合并门禁 |
|---|---|---|
| paper | AI摘要→Drive/Notion；独立提醒；Drive→可选实验 | compute 为 MEDIUM |
| decision | ADR→GitHub Issue→开发任务；独立进度通知 | GitHub/implementation 为 MEDIUM |
| wechat | 检索、提醒、确认卡；检索→可选执行 | compute 为 MEDIUM |
| checkpoint | Drive 引用、Notion指标、微信与Mac通知 | 受限Run签名入账；外部目标仍须预授权 |

LOW 表示符合已配置预授权时可自动排队，绝非任意外部写入免授权。LIVE 默认无任何 grant，不执行外部动作。所有任务同一 work_item_id/trace_id；中风险只有根任务一张审批，子分支不能被旧 Worker claim 通道领取。旧 `/api/v1/supervisor/plan` 仍提供原多步建议计划，V3 recipe 是执行编排；没有虚构 `/supervisors/plans` 或单数 `/worker/tasks/claim`。

## 状态与投递保证

每分支独立状态、generation、租约哈希、退避时间和回执。claim_token 只在领取响应返回；普通页面不见 token/hash。Worker JWT subject 必须匹配 path；能力及 node/kind 限制继续检查。LIVE grant 进一步绑定 owner/recipe/target/worker。普通浏览器被 BFF/API 拒绝 Worker 路由。

**至少一次投递 + 消费者去重 + 结果不明时对账，不提供跨平台 exactly-once。** 已知未发生写入的暂时失败按 2^attempts 退避，最多5轮；租约过期、网络写入超时、进程崩溃均进入 NEEDS_RECONCILIATION，不盲目重发。成功兄弟分支不重新排队。管理员按 generation CAS 提供至少10字符原因，选择确认未执行重试、确认失败或核验回执完成。依赖失败时下游关闭；其他独立分支继续。

PG候选：同一个事务更新 codec2 checkpoint 与 outbox.delivery_id 唯一投影。泛用旧 outbox 消费者排除这些行；V3只通过受限Worker接口 claim/finish。0006 的真实 PG、约束、跨进程与崩溃保证仍需 Gate B 验收。

新 `/api/v1/fanouts/{id}/stream` 为30秒可重连 SSE；每次读独立请求事务，Last-Event-ID 去重，每秒重新校验身份/吊销，最多每用户4流。原 `/events` SSE 与 `/events/history` JSON 保持不同语义。每次领域变更递增既有 client sync revision，保留草稿/偏好；旧 expected_revision CAS 继续拒绝覆盖。

## 签名入站

Webhook 默认503。配置文件示例见 `deploy/v3/`，秘密值只在0600常规文件读取（拒绝符号链接）。请求上限64KiB/5秒，时间偏差±300秒。

签名串为 UTF-8：`timestamp + "\n" + nonce + "\n" + Idempotency-Key + "\n" + sha256(exact_body)`，HMAC-SHA256十六进制。四个头 X-MW-Key-Id / X-MW-Timestamp / X-MW-Nonce / X-MW-Signature。nonce 安全字符12–128；业务幂等键12–256。键绑定 owner/channel/recipes；重复同包返回同一计划，变更幂等头或原始正文会拒绝，nonce 记录持久化到checkpoint并有界清理。

checkpoint LIVE 仅允许 run_ids 白名单及未来24小时内到期的专用签名键；普通浏览器不能绕过。要求已有 source_kind=live ComputeRun、step、byte_size、checkpoint_uri 和 SHA；同一步不同意图409。只登记签名调用者上报的引用，不下载权重，不把 descriptor 哈希称作真实文件验签。当前默认运行项均MOCK，真实Run接入仍阻断。

```sh
python scripts/mw_trigger.py --url http://127.0.0.1:8127 \
  --request-file deploy/v3/intent.example.json --key-id YOUR_KEY_ID \
  --key-file /run/secrets/trigger-key --idempotency-key YOUR-STABLE-INTENT-ID
```

调用失败保留原请求文件和业务幂等键；可重签新 timestamp/nonce，不能换意图冒充重试。远端HTTPS origin需显式 `--allow-remote`；禁止凭据URL、重定向、8765和非新回环端口。

## Mac 中继

```sh
python scripts/mw_outbox_dispatcher.py --url http://127.0.0.1:8127 \
  --worker-id YOUR_NEW_MAC_WORKER_ID --node-id YOUR_NEW_MAC_NODE \
  --token-file /run/secrets/mac-worker-jwt --mode SIMULATE --once
```

JWT通过受控发行方另外签发，不由脚本自签。默认仅模拟；LIVE 再加 `--mode LIVE --enable-external-writes --connectors-file /run/secrets/connectors.json` 和服务器worker grant。不安装守护进程、不自动开放端口、不接触旧业务。0600 SQLite journal 在外部副作用前持久化 STARTED；成功回执落盘后才向服务端ACK。ACK丢失只重发同一回执。崩溃不明/跨代数领取禁止自动再执行；人工核对后可归档旧 journal，不能自动删去重记录。

候选适配器：Mac指定现有列表提醒、Notion子页面、Drive意图JSON文件、GitHub Issue。用稳定 delivery_id 标记与查询辅助对账；外部写操作失败视作结果不明，不承诺第三方检索强一致。凭据从私有文件读取，无redirect或任意外部URL转发。Notion/GitHub/Drive固定官方API地址，Reminders只在macOS，通过argv传AppleScript数据，避免代码拼接。

**尚无真实执行适配器**：AI摘要、知识检索、WeChat发送、Colab/GPU启动、代码修改。对应分支可完整模拟，LIVE为不可用/对账，不假造健康、真实产物或成功通知。未来适配器须独立权限评审与测试。Drive归档的是用户提交的意图JSON，原PDF/检查点引用不代表字节已复制。

原HttpOnly/SameSite Cookie、CSRF/Origin、服务端JWT、只读断线缓存、恢复与错误状态保持。Cherry仅静态链接/手动粘贴；不访问其代码/API/鉴权/会话。绝不调用8765或生产Worker。

## 交付与验证

统一 `node scripts/mw.mjs test` 在干净源码执行正反序Python、离线dbpg、BFF、类型/lint/Vitest/build、Mock与回环Playwright、前缀及会话安全。v3专项覆盖并发幂等、门禁、分支隔离、租约、签名、codec升级、事务失败及中继崩溃。真实PG/平台/容量证据均不由模拟测试替代。详见 `GLM-DEPLOYMENT-HANDOFF.md` 与交付包精确commit报告。
