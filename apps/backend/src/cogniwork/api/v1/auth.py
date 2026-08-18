from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field

from cogniwork.api.deps import require_account
from cogniwork.api.idempotency import fingerprint, remember, replay
from cogniwork.auth.models import Account
from cogniwork.auth.service import AuthService
from cogniwork.auth.tokens import issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class AccountOut(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account: AccountOut


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def _to_response(account: Account) -> dict[str, object]:
    return TokenResponse(
        access_token=issue_token(account),
        account=AccountOut(
            id=account.id,
            email=account.email,
            created_at=account.created_at,
        ),
    ).model_dump(mode="json")


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: Request, body: RegisterRequest) -> dict[str, object]:
    body_hash = fingerprint(body.model_dump())
    cached = replay(request, body_hash)
    if cached is not None:
        return cached  # type: ignore[return-value]
    account = _auth_service(request).register(body.email, body.password)
    payload = _to_response(account)
    remember(request, body_hash, status.HTTP_201_CREATED, payload)
    return payload


@router.post("/login")
def login(request: Request, body: LoginRequest) -> dict[str, object]:
    account = _auth_service(request).login(body.email, body.password)
    return _to_response(account)


@router.get("/me")
def me(account: Annotated[Account, Depends(require_account)]) -> dict[str, object]:
    return AccountOut(
        id=account.id,
        email=account.email,
        created_at=account.created_at,
    ).model_dump(mode="json")
