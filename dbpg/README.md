# dbpg（PG_RUNTIME NOT RUN）

- `migrations/0001_init.sql`：完整 DDL（幂等唯一索引/审批 CAS/generation 禁回退触发器/outbox）
- `repository.py`：协议 + InMemory（真语义）+ PG 蓝本（显式 NotImplementedError）
- 静态断言见 tests/test_dbpg_static.py（SQL 关键约束存在性 + 蓝本不可实例运行）
- 未来 Gate（需用户单独批准）：空卷首启/角色权限/迁移回滚/加密备份恢复/pgbench/OOM/回环实测
