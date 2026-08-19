"""统一错误模型。

约定（00-conventions.md §6）：
    {"error": {"code", "message", "details", "trace_id"}}
错误码取自受控词表，不允许临时新增字符串。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """受控错误码词表（00-conventions.md §6）。"""

    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    INTERNAL_ERROR = "internal_error"


class AppError(Exception):
    """所有对外可见错误的基类。

    message 是给用户看的自然语言，不放堆栈、不放 SQL、不放凭据。
    details 是结构化补充信息，同样不得含敏感内容。
    """

    status_code: int = 500
    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: ErrorCode | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_body(self, trace_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": str(self.code),
                "message": self.message,
                "details": self.details,
                "trace_id": trace_id,
            }
        }


class InvalidRequest(AppError):
    status_code = 400
    code = ErrorCode.INVALID_REQUEST


class Unauthorized(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED


class PermissionDenied(AppError):
    """用户未授权所需 Scope。

    Runtime 收到这个错误时，不是简单地把它抛给用户，而是转为
    「向用户解释 + 给出降级方案」（00-conventions.md §4）。
    因此 details 里必须带上 scope_key 与 degraded_behavior。
    """

    status_code = 403
    code = ErrorCode.PERMISSION_DENIED


class NotFound(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND


class Conflict(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT


class RateLimited(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED


class UpstreamError(AppError):
    status_code = 502
    code = ErrorCode.UPSTREAM_ERROR


class InternalError(AppError):
    status_code = 500
    code = ErrorCode.INTERNAL_ERROR
