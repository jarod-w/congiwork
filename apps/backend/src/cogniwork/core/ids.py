"""主键生成。

约定（00-conventions.md §2）：所有主键使用 UUIDv7 —— 时间有序，便于分页与冷热分离。
不要在别处直接调用 uuid4()。
"""

from __future__ import annotations

from uuid import UUID, uuid4

from uuid_extensions import uuid7 as _uuid7


def new_id() -> UUID:
    """生成一个 UUIDv7 主键。"""
    return _uuid7()


def new_trace_id() -> str:
    """生成一次请求的 trace_id。

    与主键分开：trace_id 不入库、不需要时间有序、要短且好复制粘贴。
    单独给它一个函数是为了让「代码里不许出现裸 uuid4()」这条守护
    （tests/guards/test_no_bypass.py）保持成立 —— 一旦开了例外，
    这条守护就废了。
    """
    return uuid4().hex
