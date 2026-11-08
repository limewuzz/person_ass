"""仓储协议（PG_RUNTIME NOT RUN）。

InMemoryTaskRepo 是本地 RC 运行实现（taskengine 即其本体语义）；
PgTaskRepo 给出与迁移 SQL 对应的参数化 SQL 蓝本——连接任何真实库前为 NOT RUN。
"""
from __future__ import annotations
from typing import Protocol


class TaskRepository(Protocol):
    def insert_task(self, *, principal_id: str, capability: str, capability_version: int,
                    resource_id: str, idempotency_key: str, request_hash: str,
                    origin_channel: str, requires_approval: bool, risk: str) -> str: ...
    def find_by_idempotency(self, principal_id, capability, capability_version,
                            idempotency_key): ...
    def cas_update_state(self, task_id: str, expect_state: str, new_state: str) -> bool:
        """UPDATE tasks SET state=:new WHERE id=:id AND state=:expect RETURNING 1 —— 行级 CAS。"""
    def conditional_finish(self, task_id: str, generation: int, lease_token_hash: str,
                           outcome: str) -> bool:
        """条件 UPDATE ... WHERE generation=:g AND lease_token_hash=:h RETURNING（迟到拒绝）。"""


class InMemoryTaskRepo:
    """本地实现委托 TaskEngine（真实语义见 backend/taskengine.py 与测试矩阵）。"""


class PgTaskRepo(TaskRepository):
    """PG 蓝本（NOT RUN；连接串经 /run/secrets，绝不入 env/argv）。"""
    def __init__(self, conn):  # conn: psycopg/asyncpg 连接（部署 Gate 后注入）
        self._c = conn

    def insert_task(self, **kw) -> str:
        # ON CONFLICT (principal_id, capability, capability_version, idempotency_key) DO NOTHING
        # RETURNING id —— 100 并发唯一行由唯一索引保证
        raise NotImplementedError("PG_RUNTIME NOT RUN")

    def cas_update_state(self, task_id, expect_state, new_state) -> bool:
        raise NotImplementedError("PG_RUNTIME NOT RUN")

    def conditional_finish(self, task_id, generation, lease_token_hash, outcome) -> bool:
        raise NotImplementedError("PG_RUNTIME NOT RUN")
