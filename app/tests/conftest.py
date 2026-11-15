"""Shared fixtures for the tool tests."""

import pytest
from fakeredis.aioredis import FakeRedis

from app.config import settings
from app.core import jr_store, progress, translation_cache


@pytest.fixture
def fake_redis(monkeypatch):
    """Point every Redis-backed store at an in-memory server."""
    client = FakeRedis()

    async def _get_redis():
        return client

    monkeypatch.setattr(jr_store, "_get_redis", _get_redis)
    monkeypatch.setattr(progress, "_get_redis", _get_redis)
    monkeypatch.setattr(translation_cache, "_get_redis", _get_redis)
    return client


@pytest.fixture(autouse=True)
def runtime_settings(monkeypatch):
    """Runtime settings against a fresh in-memory store, cache cleared.

    Without this, the 2-second in-process cache leaks provider values
    between tests and monkeypatched `settings.translation.*` defaults are
    never re-read. Sync FakeRedis — runtime_settings is a sync client.
    """
    from fakeredis import FakeRedis as SyncFakeRedis

    from app.core import runtime_settings as rs

    client = SyncFakeRedis(decode_responses=True)
    monkeypatch.setattr(rs, "_client", lambda: client)
    rs.invalidate()
    return client


@pytest.fixture
def password(monkeypatch):
    """Configure the shared write password."""
    monkeypatch.setattr(settings.app, "password", "secret")
    return "secret"
