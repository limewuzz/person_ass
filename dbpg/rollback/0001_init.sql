-- DESTRUCTIVE: disposable Gate B database only; stop API first.
DROP TABLE outbox;
DROP TABLE audit_events;
DROP TABLE approvals;
DROP TABLE task_attempts;
DROP TABLE task_events;
DROP TABLE tasks;
DROP TABLE work_items;
DROP TABLE target_change_log;
DROP TABLE approved_probe_targets;
DROP TABLE resources;
DROP TABLE principals;
DROP FUNCTION resources_write_rev_guard();
DROP SEQUENCE resource_generation_seq;
