"""Envelope encryption for tool credentials (P0-05 §5).

Each row has its own DEK. The DEK is wrapped by a master key from settings.
Plaintext exists only for the duration of one call — never logged, never
traced, never written back.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cogniwork.core.errors import InternalError

_TOKEN_KEYS = (
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "client_secret",
    "client_id",
    "password",
    "authorization",
)


def normalize_master_key(raw: str) -> bytes:
    text = (raw or "").strip().encode()
    if not text:
        raise InternalError("Vault master key is not configured.")
    return hashlib.sha256(text).digest()


def seal(plaintext: bytes, master_key: bytes) -> tuple[bytes, bytes, int]:
    dek = secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    ciphertext = nonce + AESGCM(dek).encrypt(nonce, plaintext, None)
    wrap_nonce = secrets.token_bytes(12)
    wrapped = wrap_nonce + AESGCM(master_key).encrypt(wrap_nonce, dek, None)
    return ciphertext, wrapped, 1


def open_sealed(ciphertext: bytes, dek_wrapped: bytes, master_key: bytes) -> bytes:
    wrap_nonce, wrapped = dek_wrapped[:12], dek_wrapped[12:]
    dek = AESGCM(master_key).decrypt(wrap_nonce, wrapped, None)
    nonce, body = ciphertext[:12], ciphertext[12:]
    return AESGCM(dek).decrypt(nonce, body, None)


def seal_bundle(bundle: dict[str, Any], master_key: bytes) -> tuple[bytes, bytes, int]:
    payload = json.dumps(bundle, separators=(",", ":")).encode()
    return seal(payload, master_key)


def open_bundle(ciphertext: bytes, dek_wrapped: bytes, master_key: bytes) -> dict[str, Any]:
    raw = open_sealed(ciphertext, dek_wrapped, master_key)
    data = json.loads(raw.decode())
    if not isinstance(data, dict):
        raise InternalError("Credential bundle is corrupt.")
    return data


def redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).lower() in _TOKEN_KEYS:
                out[key] = "[redacted]"
            else:
                out[key] = redact_obj(item)
        return out
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str) and _looks_like_secret(value):
        return "[redacted]"
    return value


def redact_text(text: str) -> str:
    out = text
    for key in _TOKEN_KEYS:
        # Keep the key name; strip anything that looks like an assignment.
        out = out.replace(f"{key}=", f"{key}=[redacted]")
    return out


def _looks_like_secret(value: str) -> bool:
    if value.startswith("ya29.") or value.startswith("gho_") or value.startswith("ghp_"):
        return True
    if value.startswith("cw-canary-"):
        return True
    return False
