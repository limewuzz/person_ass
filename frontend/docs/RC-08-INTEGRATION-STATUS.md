# Integration status

用户已授权修复独立后端副本，原GLM交付包和生产未变。最终联合判定以evidence/release/integrated-release.json为准。

IMPLEMENTED：前端22模板；实际loopback新API；服务端强制的模拟策略、完整请求幂等、审批/Worker/结果闭环；不可直写的资源与共享提交锁；同源session、CSRF与共享契约校验。
TESTED：后端完整回归双顺序、43操作schema、35项独立检查、BFF、前端单元/契约、8个MSW及7个实际API浏览器用例；四屏宽、键盘/基本WCAG/reduced motion、错误/权限/断网。数量和退出码见JUnit/机器报告。
DEPLOYED：NO。
APPROVED：LOCAL ONLY；生产NO。

新任务只能作用于local-ledger，不能调用模型、shell、旧服务或外部平台。成功产物是实际内存字节；失联已批任务进入待对账、不盲目重排。重启内存API会丢失账本；没有伪装成PG恢复。
