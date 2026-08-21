"""OAuth start/callback + credential vault (P0-05 M2).

This module writes connections. Whether a later tool call runs is still
decided only on the runtime tool path.
"""

from __future__ import annotations

import base64
import secrets
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from cogniwork.consent.registry import get_registry
from cogniwork.core.clock import now
from cogniwork.core.config import Settings, get_settings
from cogniwork.core.errors import AppError, InvalidRequest, NotFound
from cogniwork.tools.catalog import ToolCatalog, load_catalog
from cogniwork.tools.http import HttpTransport, StubTransport
from cogniwork.tools.store import (
    InMemoryToolStore,
    OAuthState,
    ToolConnection,
    ToolCredential,
    new_connection,
)
from cogniwork.tools.vault import normalize_master_key, open_bundle, seal_bundle


class ToolService:
    def __init__(
        self,
        store: Any | None = None,
        *,
        catalog: ToolCatalog | None = None,
        settings: Settings | None = None,
        transport: HttpTransport | None = None,
        consent: Any | None = None,
        audit: Any | None = None,
    ) -> None:
        self.store = store or InMemoryToolStore()
        self.catalog = catalog or load_catalog()
        self.settings = settings or get_settings()
        self.transport = transport or (
            StubTransport() if self.settings.oauth_stub else HttpTransport()
        )
        self.consent = consent
        self.audit = audit
        self._master = normalize_master_key(self.settings.vault_master_key)

    def providers(self, locale: str, fallback: str) -> list[dict[str, Any]]:
        registry = get_registry()
        out = []
        for provider in self.catalog.providers:
            scopes = []
            for key in self.catalog.scopes_for_provider(provider.id):
                spec = registry.get(key)
                if spec is None:
                    continue
                copy = spec.copy_for(locale, fallback)
                scopes.append(
                    {
                        "key": spec.key,
                        "risk": spec.risk.value,
                        "trust_level": spec.trust_level.value,
                        "display_name": copy.display_name,
                        "degraded_behavior": copy.degraded_behavior,
                        "oauth_scopes": list(spec.third_party_scopes),
                    }
                )
            out.append(
                {
                    "id": provider.id,
                    "display_name": provider.display_name,
                    "oauth_kind": provider.oauth_kind,
                    "scopes": scopes,
                    "tools": [
                        {"name": t.name, "risk": t.risk.value, "scope_key": t.scope_key}
                        for t in provider.tools
                    ],
                }
            )
        return out

    def list_connections(self, user_id: UUID) -> list[dict[str, Any]]:
        return [connection_out(item) for item in self.store.list_connections(user_id)]

    def start_connect(
        self,
        user_id: UUID,
        provider_id: str,
        scopes: list[str] | None,
        *,
        surface: str = "web",
    ) -> dict[str, Any]:
        provider = self.catalog.provider(provider_id)
        requested = scopes or [
            key for key in self.catalog.scopes_for_provider(provider_id) if key.endswith(":read")
        ]
        allowed = set(self.catalog.scopes_for_provider(provider_id))
        extra = [key for key in requested if key not in allowed]
        if extra:
            raise InvalidRequest(
                "This connection does not offer that permission yet.",
                details={"scopes": extra},
            )
        oauth_scopes = self.catalog.oauth_scopes_for(requested)
        if self.settings.oauth_stub:
            return self._complete_stub(user_id, provider.id, requested, oauth_scopes, surface)
        state = secrets.token_urlsafe(24)
        self.store.put_state(
            OAuthState(
                state=state,
                user_id=user_id,
                provider=provider.id,
                granted_scopes=requested,
                created_at=now(),
            )
        )
        return {
            "status": "pending",
            "authorization_url": self._authorize_url(provider.oauth_kind, oauth_scopes, state),
            "state": state,
        }

    def oauth_callback(self, *, code: str, state: str, surface: str = "web") -> ToolConnection:
        pending = self.store.pop_state(state)
        if pending is None:
            raise NotFound("This sign-in link is no longer valid.")
        provider = self.catalog.provider(pending.provider)
        oauth_scopes = self.catalog.oauth_scopes_for(pending.granted_scopes)
        bundle, label = self._exchange(provider.oauth_kind, code, oauth_scopes)
        return self._persist(
            pending.user_id,
            provider.id,
            pending.granted_scopes,
            oauth_scopes,
            bundle,
            label,
            surface,
        )

    def patch_scopes(
        self,
        user_id: UUID,
        connection_id: UUID,
        scopes: list[str],
        *,
        surface: str = "web",
    ) -> dict[str, Any]:
        item = self.store.get_connection(user_id, connection_id)
        if item is None:
            raise NotFound("Connection not found.")
        return self.start_connect(user_id, item.provider, scopes, surface=surface)

    def disconnect(
        self, user_id: UUID, connection_id: UUID, *, surface: str = "web"
    ) -> dict[str, Any]:
        """断开：撤第三方授权 + 物理删凭据 + 撤 Scope（P0-05 §5、§10 验收 2）。

        顺序不能反。撤销要用 token，删完再撤就没得撤了 —— 那种做法下用户点了
        「断开」，Google / GitHub 那边的授权还活到过期为止，用户看到的和实际
        发生的不是一回事。上游撤销失败也照样删本地凭据：本地不留才是我们能
        保证的部分，失败原因记进 `last_error` 并回给调用方。
        """
        item = self.store.get_connection(user_id, connection_id)
        if item is None:
            raise NotFound("Connection not found.")
        revoked, detail = self._revoke_upstream(item)
        self.store.delete_credential(item.id)
        item.status = "revoked"
        item.updated_at = now()
        item.last_error = None if revoked else {"code": "revoke_failed", "detail": detail}
        self.store.upsert_connection(item)
        if self.consent is not None:
            for scope_key in item.granted_scopes:
                self.consent.revoke(user_id=str(user_id), scope_key=scope_key, surface=surface)
        return {"upstream_revoked": revoked, "detail": detail}

    def _revoke_upstream(self, item: ToolConnection) -> tuple[bool, str]:
        """调第三方的 revoke 端点。token 只在这一次调用期间存在于内存。"""
        cred = self.store.get_credential(item.id)
        if cred is None:
            return True, "no_credential_stored"
        try:
            bundle = open_bundle(cred.ciphertext, cred.dek_wrapped, self._master)
        except Exception:
            # 解不开就撤不了，但也不该挡住断开。
            return False, "credential_unreadable"
        kind = self.catalog.provider(item.provider).oauth_kind
        # refresh token 优先：Google 撤 refresh token 会一并失效由它派生的 access token。
        token = str(bundle.get("refresh_token") or bundle.get("access_token") or "")
        if not token:
            return True, "no_token_stored"
        try:
            return self._call_revoke(kind, token)
        except AppError as exc:
            return False, exc.code.value if hasattr(exc.code, "value") else str(exc.code)
        except Exception as exc:
            return False, type(exc).__name__

    def _call_revoke(self, kind: str, token: str) -> tuple[bool, str]:
        if kind == "google":
            # https://oauth2.googleapis.com/revoke?token=…（官方文档的形式）
            self.transport.request(
                "POST",
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return True, "revoked"
        if kind == "github":
            # OAuth App 的授权撤销走 client 凭据的 Basic auth，不是用户 token。
            self.transport.request(
                "DELETE",
                f"https://api.github.com/applications/{self.settings.github_client_id}/grant",
                headers={
                    "Authorization": _basic_auth(
                        self.settings.github_client_id, self.settings.github_client_secret
                    ),
                    "Accept": "application/vnd.github+json",
                },
                json_body={"access_token": token},
            )
            return True, "revoked"
        if kind == "notion":
            # Notion 没有 token 撤销端点（截至 2026-08 的 API）。
            # 用户要彻底断开需要在 Notion 侧移除集成 —— 这一点由 UI 明示，
            # 不假装我们撤掉了（连接管理页 §8 的断开确认文案）。
            return False, "provider_has_no_revoke_endpoint"
        return False, "unknown_oauth_kind"

    def token_for(self, user_id: UUID, provider: str) -> str | None:
        item = self.store.active_for_provider(user_id, provider)
        if item is None:
            return None
        cred = self.store.get_credential(item.id)
        if cred is None:
            return None
        bundle = open_bundle(cred.ciphertext, cred.dek_wrapped, self._master)
        token = bundle.get("access_token")
        item.last_used_at = now()
        self.store.upsert_connection(item)
        return str(token) if token else None

    def activity(self, user_id: UUID, connection_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        item = self.store.get_connection(user_id, connection_id)
        if item is None:
            raise NotFound("Connection not found.")
        if self.audit is None or not hasattr(self.audit, "list_for_user"):
            return []
        prefix = f"tool:{item.provider}:"
        rows = []
        for row in self.audit.list_for_user(str(user_id), limit=200):
            key = row.get("scope_key") or ""
            action = str(row.get("action") or "")
            if key.startswith(prefix) or action.startswith(f"{item.provider}."):
                rows.append(
                    {
                        "id": row.get("id"),
                        "action": row.get("action"),
                        "result": row.get("result"),
                        "created_at": (
                            row["created_at"].isoformat()
                            if hasattr(row.get("created_at"), "isoformat")
                            else row.get("created_at")
                        ),
                        "target_digest": row.get("target_digest"),
                    }
                )
            if len(rows) >= limit:
                break
        return rows

    def _complete_stub(
        self,
        user_id: UUID,
        provider: str,
        scopes: list[str],
        oauth_scopes: list[str],
        surface: str,
    ) -> dict[str, Any]:
        bundle = {
            "access_token": "cw-canary-access",
            "refresh_token": "cw-canary-refresh",
            "token_type": "Bearer",
        }
        labels = {
            "gcal": "work@example.com",
            "gmail": "work@example.com",
            "notion": "Example workspace",
            "github": "example",
        }
        item = self._persist(
            user_id, provider, scopes, oauth_scopes, bundle, labels.get(provider), surface
        )
        return {"status": "active", "connection": connection_out(item)}

    def _persist(
        self,
        user_id: UUID,
        provider: str,
        scopes: list[str],
        oauth_scopes: list[str],
        bundle: dict[str, Any],
        label: str | None,
        surface: str,
    ) -> ToolConnection:
        existing = self.store.active_for_provider(user_id, provider)
        if existing is not None and existing.account_label == label:
            item = existing
            item.granted_scopes = scopes
            item.oauth_scopes = oauth_scopes
            item.status = "active"
            item.updated_at = now()
        else:
            item = new_connection(user_id, provider, scopes, oauth_scopes, label)
        self.store.upsert_connection(item)
        ciphertext, wrapped, version = seal_bundle(bundle, self._master)
        self.store.put_credential(
            ToolCredential(
                connection_id=item.id,
                ciphertext=ciphertext,
                dek_wrapped=wrapped,
                key_version=version,
                updated_at=now(),
            )
        )
        if self.consent is not None:
            registry = get_registry()
            for scope_key in scopes:
                spec = registry.require(scope_key)
                self.consent.grant(
                    user_id=str(user_id),
                    scope_key=scope_key,
                    skip_repeat_prompt=True,
                    surface=surface,
                    consent_text_version=spec.consent_text_version,
                )
        return item

    def _exchange(
        self, kind: str, code: str, oauth_scopes: list[str]
    ) -> tuple[dict[str, Any], str | None]:
        if kind == "google":
            resp = self.transport.request(
                "POST",
                "https://oauth2.googleapis.com/token",
                json_body={
                    "code": code,
                    "client_id": self.settings.google_client_id,
                    "grant_type": "authorization_code",
                    "redirect_uri": self._redirect_uri(),
                    "scope": " ".join(oauth_scopes),
                },
            )
            bundle = dict(resp.data or {})
            info = self.transport.request(
                "GET",
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {bundle.get('access_token')}"},
            )
            return bundle, (info.data or {}).get("email")
        if kind == "notion":
            resp = self.transport.request(
                "POST",
                "https://api.notion.com/v1/oauth/token",
                json_body={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri(),
                },
            )
            bundle = dict(resp.data or {})
            return bundle, (bundle.get("workspace_name") or "Notion")
        if kind == "github":
            resp = self.transport.request(
                "POST",
                "https://github.com/login/oauth/access_token",
                json_body={
                    "client_id": self.settings.github_client_id,
                    "code": code,
                    "redirect_uri": self._redirect_uri(),
                },
            )
            bundle = dict(resp.data or {})
            info = self.transport.request(
                "GET",
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {bundle.get('access_token')}"},
            )
            return bundle, (info.data or {}).get("login")
        raise InvalidRequest("Unknown OAuth provider.")

    def _authorize_url(self, kind: str, oauth_scopes: list[str], state: str) -> str:
        redirect = self._redirect_uri()
        if kind == "google":
            params = {
                "client_id": self.settings.google_client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": " ".join(oauth_scopes),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
            return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        if kind == "notion":
            params = {
                "client_id": self.settings.notion_client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "owner": "user",
                "state": state,
            }
            return "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)
        if kind == "github":
            params = {
                "client_id": self.settings.github_client_id,
                "redirect_uri": redirect,
                "scope": ",".join(oauth_scopes),
                "state": state,
            }
            return "https://github.com/login/oauth/authorize?" + urlencode(params)
        raise InvalidRequest("Unknown OAuth provider.")

    def _redirect_uri(self) -> str:
        return self.settings.public_base_url.rstrip("/") + "/api/v1/tools/oauth/callback"


def _basic_auth(user: str, secret: str) -> str:
    raw = f"{user}:{secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def connection_out(item: ToolConnection) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "provider": item.provider,
        "account_label": item.account_label,
        "granted_scopes": item.granted_scopes,
        "oauth_scopes": item.oauth_scopes,
        "status": item.status,
        "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
