-- PROPOSAL v3：最小权限角色拆分（评审 R2 BLOCK-02）
-- 由官方镜像 /docker-entrypoint-initdb.d 在首次初始化时以 mwcp_bootstrap 执行（一次性）。
-- 密码值不写在此文件：通过 psql 变量注入（部署 SOP：
--   docker compose exec -T ... 或临时容器内
--   psql -v app_pw="`cat /run/secrets/mwcp_pg_app_password`" ...
-- 演示用 \getvector 不可用时由部署脚本模板替换 :app_pw/:mig_pw）

-- 1) 迁移账户：DDL 权限（Alembic 专用，不日常运行）
CREATE ROLE mwcp_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CREATE ON DATABASE control_plane TO mwcp_migrator;

-- 2) 应用运行账户：仅 DML + 序列，无 DDL/建库/建角色/超级用户
CREATE ROLE mwcp_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE control_plane TO mwcp_app;

-- 3) 迁移完成后由 Alembic 迁移本身补齐：
--    GRANT USAGE ON SCHEMA public TO mwcp_app;
--    GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO mwcp_app;
--    GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO mwcp_app;
--    ALTER DEFAULT PRIVILEGES FOR ROLE mwcp_migrator IN SCHEMA public
--      GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO mwcp_app;

-- 4) bootstrap 账户密码轮换并降权（部署 SOP 末步）：
--    ALTER ROLE mwcp_bootstrap NOLOGIN;  -- 保留仅灾难恢复用，或直接 DROP
