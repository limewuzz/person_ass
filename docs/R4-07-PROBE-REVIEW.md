# R4-07 · 探针审查更新（SSRF 防护版）

承接 R3 的 P1-06-PROBE-REVIEW.md；本轮新增 SSRF/重定向/并发防护与负向测试（backend/tests/test_probes.py 后 8 项）。

## 1. SSRF 防护三层（probes.py `validate_probe_target`）

1. **URL 层**：scheme 仅 http/https（file/gopher 等拒）；URL 内嵌凭据拒；无主机拒。
2. **主机层**：云元数据字面量黑名单（169.254.169.254 / metadata.google.internal / metadata.goog / fd00:ec2::254 / 100.100.100.100）；`production_mode=True` 时仅放行 `PRODUCTION_ALLOWED_HOSTS`（**当前为空集 → 设计上不可能探测任何生产目标**）。
3. **解析层**：getaddrinfo 全量结果逐 IP 校验——回环需显式 `allow_loopback=True`（仅测试夹具）；link-local/private/reserved/multicast/unspecified 一律拒。

测试：元数据×3、私网×2、回环需旗标、scheme/凭据、生产白名单空集全拒——全部负向断言通过。

## 2. 重定向与并发

- `follow_redirects=False`；3xx → 显式 `redirect` 态（health=unknown，note 标注 not followed）——测试用 302→元数据地址的目标证明不跟随。
- `run_batch(max_concurrency)` 有界线程池；max=1 时双慢目标串行（elapsed 断言）；线程随 with 块回收。

## 3. 残余风险（如实）

- **DNS 重绑定**：预解析校验是缓解而非消除（TOCTOU：校验后连接前解析可能变化）。生产化时叠加：固定解析 IP 直连 + Host 头校验，或经出站代理白名单。此项列入 P1-06 生产化门槛。
- IPv6 目标：解析层已覆盖（ip_address 判定 is_private 等对 v6 生效）；未做 v6 字面量专项测试（列入补测）。

## 4. 证据分级不变

Mock 目标（127.0.0.1 临时端口，allow_loopback=True 显式声明）；**零生产目标、零 Cherry 目标**（Cherry 域名在 PRODUCTION_ALLOWED_HOSTS 机制下默认不可能进入）。
