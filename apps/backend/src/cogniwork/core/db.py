"""Postgres 连接池。

生产路径用 psycopg 连接池；单测走 memory store 时不会碰到这里。
连接失败要在启动时暴露，不要拖到第一次授权检查。
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings


def open_pool(settings: Settings) -> ConnectionPool:
    # dict_row 让 store 用列名取值，避免 INSERT/SELECT 列序微调时静默错位。
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        open=True,
    )
