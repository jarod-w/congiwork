"""当前登录账号。

不要把这个函数命名为 check —— tests/guards/test_no_bypass.py 要求
ConsentService.check 是全代码库唯一的 check() 定义。
"""

from __future__ import annotations

from fastapi import Request

from cogniwork.auth.models import Account
from cogniwork.auth.service import AuthService
from cogniwork.auth.tokens import parse_token
from cogniwork.core.errors import Unauthorized


def require_account(request: Request) -> Account:
    header = request.headers.get("authorization")
    if header is None or not header.lower().startswith("bearer "):
        raise Unauthorized("Sign in to continue.")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise Unauthorized("Sign in to continue.")
    account_id = parse_token(token)
    auth_service: AuthService = request.app.state.auth_service
    account = auth_service.get(account_id)
    if account is None:
        raise Unauthorized("Sign in to continue.")
    return account
