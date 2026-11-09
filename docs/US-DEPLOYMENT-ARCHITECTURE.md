# 美国服务器部署架构（设计方案——未部署）

**状态：DESIGN / NOT_DEPLOYED。** 生产部署需独立授权 + Gate B 通过。

## 1. 目标架构

```
互联网
  └─ 美国 50.114.172.213（6C/11GiB，现有 nginx + 18 容器）
       └─ nginx（现有，新增一个 server/location 块——独立审批）
            └─ 127.0.0.1:8129 → mwcp-api 容器（FastAPI+BFF 一体）
                                      ├─ mwcp-net（internal:true）
                                      │    └─ mwcp-pg:5432（PG 16，零端口发布）
                                      └─ 前端静态文件 → nginx 直接 serve（dist/ 只读挂载）
```

### 资源预算（设计值——**Gate B 实测后填真值**）

| 组件 | 预算 | 依据 |
|---|---|---|
| mwcp-api | ≤256MiB | Mac 实测 RSS 51.7MB ×余量 |
| mwcp-pg | ≤640MiB | shared_buffers 128M + 20 conn |
| 前端静态 | ≈0（nginx 已有） | dist/ 555KB |
| **合计** | **≤1GiB（目标 1.5GiB 含余量）** | vs 现有 available ≈5.9GiB（2026-11-08 实测） |

**明确不引入**：Redis / Prometheus / Loki / Kubernetes / 消息队列 / 任何重型 Worker。

## 2. 生产身份认证（BFF 模式）

- **外部**：浏览器 → HTTPS → nginx → BFF（HttpOnly+Secure+SameSite=Strict Cookie；CSRF token；精确 Origin 校验——本地 BFF 已实现同构逻辑，生产加固 Secure 标记+TLS）
- **内部**：BFF → API（进程内调用；服务账号 JWT，kid 轮换表走 /run/secrets）
- **OIDC**（可选，P2+）：单用户场景默认**本地密码+ TOTP**方案（bcrypt + 32 字节盐 + 6 位 TOTP）；JTI 持久化黑名单（PG 表，随 Gate B 入库）——不引入外部 IdP 依赖
- **会话撤销**：服务端 session 表（PG）+ JTI 黑名单 + cookie 即时失效三通道

## 3. HTTPS 与网络

- TLS：复用宿主 LE 证书链（certbot 已在）；新增 `cp.magicworkshop.fun` 子域（DNS+证书=独立审批项）
- nginx 增量（独立审批）：`location /cp/ { proxy_pass http://127.0.0.1:8129/; }` + HSTS + 现有访问日志格式
- CSP/安全头：`X-Frame-Options=DENY` `X-Content-Type-Options=nosniff` `Referrer-Policy=strict-origin`
- **不修改**：现有任何 server 块/端口/443 配置（增量式，nginx -t 预检 + reload 仅新配置）

## 4. 审计/健康/监控（轻量）

- 审计：PG `audit_events` 表（已有 DDL）+ 每日 dump 归档（与备份同管道）
- 健康：`/health/live`（进程）+ `/health/ready`（**诚实**：PG SELECT 1 + 迁移版本 + auth——Gate B 后 readiness 的 database 项才可变 ok）
- 监控：**无 Prometheus**——`mwcp-api` 内置 `/metrics-json`（进程 RSS/事件计数/DB pool 状态）+ cron 每小时写宿主日志（轮转 14 天）+ 异常退出 systemd 自动重启+邮件通知（复用宿主 ssmtp 如有）

## 5. 备份/恢复/升级/回滚 SOP

| 流程 | 方法 | 触发 |
|---|---|---|
| 备份 | 每日 03:30 UTC `pg_dump -Fc` + `pg_dumpall --globals-only` → AES-256+HMAC 加密 → Mac 拉取（方向：Mac→US scp） | cron timer（新增=独立审批） |
| 恢复 | 全新卷 → 验签 → 解密 → globals → 建库 → `pg_restore --exit-on-error` → 对象/行数/权限断言 → 应用只读验证 | 手动（月度演练） |
| 升级 | 新版本容器镜像（digest 锁定）→ `docker compose up -d mwcp-api`（PG 不动）→ readiness 通过 → 切流量 | 版本发布 |
| 回滚 | 应用：`docker compose up -d --no-deps mwcp-api`（前一版本 tag）；**数据库禁止降级**（需恢复演练验证过的兼容快照才可回退 schema） | 升级失败 |

**RPO=24h（日备）/ RTO=15min（演练度量，Gate B E12 定真值）。**

## 6. 部署步骤清单（未来——每步独立审批）

1. Gate B 通过 → 用户批准生产部署范围
2. 宿主前置检查（名字冲突/磁盘/内存余量）
3. secrets 文件生成（0600 root）+ compose `config --quiet` 静态校验
4. PG 首启（独立网络/卷）→ 迁移 → 角色权限正反向测试
5. api 容器起（`127.0.0.1:8129`）→ readiness 200（database=ok）
6. nginx 增量配置 + `-t` + reload → 外部 HTTPS 验证
7. DNS `cp.magicworkshop.fun` 切入
8. 7 天观察期（无问题才算 DEPLOYED）

## 7. 与现有业务隔离边界

| 禁触 | 验证方法 |
|---|---|
| rakazo 5 容器/库 | 部署前后 `docker ps --filter name=rakazo` + stats RSS 差 <5% |
| cliproxy/魔坊/nginx 站点 | nginx -t 零 diff 现有 vhost；httpstatus 抽查 |
| 8765/EventKit/Rakazo 调度 | 不发任何请求到旧系统端口 |
| Caddy/frp/UCloud/腾讯 | 完全不登录不改配置 |
