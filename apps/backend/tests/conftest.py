from __future__ import annotations

import pytest

from cogniwork.consent.registry import load_registry


@pytest.fixture(scope="session")
def registry():
    return load_registry()
