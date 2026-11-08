-- PG v4 权限正反例测试（静态文件：仅在获批准的隔离环境执行；本地未运行 → NOT RUN）
-- 预期矩阵见 perm-matrix.md。执行方式（隔离演练）：
--   psql "postgres://mwcp_app@localhost/control_plane" -f perm-negative-tests.sql
-- 每条注释写明预期（应失败/应成功）。

-- 【应成功】app 读写迁移产生的表（需先由 migrator 建表并跑 Alembic）
-- SELECT 1;
BEGIN;
-- 【应失败】app 建表
CREATE TABLE _perm_probe_should_fail(id int);          -- 预期 ERROR: permission denied
-- 【应失败】app 删表
DROP TABLE tasks;                                        -- 预期 ERROR: permission denied
-- 【应失败】app 建/删角色
CREATE ROLE _should_fail;                               -- 预期 ERROR: permission denied
-- 【应成功】migrator（另一连接）建表后，app 可 INSERT/SELECT
ROLLBACK;
