"""Bearer JWT 的签发与解析（00-conventions.md §6）。"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import jwt

from cogniwork.core import clock
from cogniwork.core.config import get_settings
from cogniwork.core.errors import Unauthorized

from .models import Account


def issue_token(account: Account) -> str:
    settings = get_settings()
    issued = clock.now()
    payload = {
        "sub": str(account.id),
        "email": account.email,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=settings.jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def parse_token(token: str) -> UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise Unauthorized("This session has expired. Sign in again.") from None
    except jwt.InvalidTokenError:
        raise Unauthorized("Sign in to continue.") from None

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise Unauthorized("Sign in to continue.")
    try:
        return UUID(sub)
    except ValueError:
        raise Unauthorized("Sign in to continue.") from None
