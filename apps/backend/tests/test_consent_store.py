"""Postgres + Redis 落库路径。本地没有基础设施时 skip。"""

from __future__ import annotations

import pytest

from cogniwork.consent.models import ConsentAction, ConsentDecision, Risk
from cogniwork.consent.service import ConsentService
from cogniwork.consent.store import PostgresConsentStore
from cogniwork.core.config import get_settings
from cogniwork.core.ids import new_id
from cogniwork.migrate import apply_migrations


def _postgres_configured() -> bool:
    return get_settings().store_backend == "postgres"


pytestmark = pytest.mark.skipif(
    not _postgres_configured(),
    reason="COGNIWORK_STORE_BACKEND is not postgres",
)


@pytest.fixture(scope="module")
def migrated():
    apply_migrations()


def test_migrate_is_idempotent(migrated):
    again = apply_migrations()
    assert again == []


def test_consent_roundtrip_invalidates_redis(migrated, registry):
    settings = get_settings()
    from cogniwork.core.db import open_pool
    from cogniwork.core.redis import open_redis

    pool = open_pool(settings)
    redis = open_redis(settings)
    store = PostgresConsentStore(pool, redis)
    try:
        user_id = str(new_id())
        scope_key = "tool:notion:read"
        assert store.current(user_id, scope_key) is None

        store.append(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction.GRANTED,
            always_allow=True,
            surface="web",
            consent_text_version="1",
        )
        granted = store.current(user_id, scope_key)
        assert granted is not None
        assert granted.action is ConsentAction.GRANTED
        svc = ConsentService(store, registry)
        assert svc.check(user_id, scope_key, Risk.READ) is ConsentDecision.ALLOW

        if redis is not None:
            assert redis.hexists(f"consent:{user_id}", scope_key)

        store.append(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction.REVOKED,
            always_allow=False,
            surface="web",
            consent_text_version="1",
        )
        # 写时失效：撤销后立即 DENY —— P0-07 §13 验收 4
        assert svc.check(user_id, scope_key, Risk.READ) is ConsentDecision.DENY
        if redis is not None:
            assert not redis.exists(f"consent:{user_id}")
    finally:
        store.clear()
        pool.close()
        if redis is not None:
            redis.close()


def test_redis_miss_falls_back_to_materialized_view(migrated):
    settings = get_settings()
    from cogniwork.core.db import open_pool
    from cogniwork.core.redis import open_redis

    pool = open_pool(settings)
    redis = open_redis(settings)
    store = PostgresConsentStore(pool, redis)
    try:
        user_id = str(new_id())
        scope_key = "tool:gmail:read"
        store.append(
            user_id=user_id,
            scope_key=scope_key,
            action=ConsentAction.GRANTED,
            always_allow=True,
            surface="web",
            consent_text_version="1",
        )
        if redis is not None:
            redis.delete(f"consent:{user_id}")
        state = store.current(user_id, scope_key)
        assert state is not None
        assert state.action is ConsentAction.GRANTED
    finally:
        store.clear()
        pool.close()
        if redis is not None:
            redis.close()
