\set target random(1,100)
BEGIN;
UPDATE gateb_bench SET n=n+1 WHERE id=:target;
END;
