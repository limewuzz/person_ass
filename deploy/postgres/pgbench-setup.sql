-- Authorized disposable Gate B DB only, execute as mwcp_migrator.
CREATE TABLE gateb_bench(id INTEGER PRIMARY KEY, n BIGINT NOT NULL DEFAULT 0);
INSERT INTO gateb_bench(id) SELECT generate_series(1,100);
