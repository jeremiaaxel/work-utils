"""Runtime settings — provider choices editable from the web UI.

`.env` (via app.config) supplies the defaults; values saved on the Settings
page are stored in Redis and override them. Both the web process and the
worker read the same keys, so a change applies to new jobs within the cache
TTL — no restart.

Reads never raise: when Redis is unreachable the defaults are served, so an
outage degrades to `.env` behaviour instead of breaking translation or OCR.
"""

from __future__ import annotations

import logging
import os
import time
from typing import cast

import redis

from app.config import settings

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_DB = 4  # next to the page store and the translation cache
_KEY = "ws:runtime-settings"

_TTL_SECONDS = 2.0  # how long a process may serve its cached copy

# Every field that may be stored, with its .env default.
_FIELDS = (
    "translation_primary",
    "translation_fallback",
    "deepl_api_key",
    "lingva_url",
    "ocr_engine",
)


def _defaults() -> dict[str, str]:
    return {
        "translation_primary": settings.translation.primary,
        "translation_fallback": settings.translation.fallback,
        "deepl_api_key": settings.translation.deepl_api_key,
        "lingva_url": settings.translation.lingva_url,
        "ocr_engine": "paddle",
    }


# In-process cache: provider calls happen per line, and a Redis roundtrip
# for every one of them would be waste.
_cached: dict[str, str] | None = None
_cached_at = 0.0


def _client() -> redis.Redis:
    """A sync client — settings are read from worker threads, not just async
    handlers."""
    if not hasattr(_client, "_c"):
        _client._c = redis.Redis.from_url(  # type: ignore[attr-defined]
            f"{REDIS_URL}/{_DB}", decode_responses=True
        )
    return _client._c  # type: ignore[attr-defined]


def get_all() -> dict[str, str]:
    """The effective settings: runtime values over the `.env` defaults."""
    global _cached, _cached_at
    now = time.monotonic()
    if _cached is not None and now - _cached_at < _TTL_SECONDS:
        return _cached
    out = _defaults()
    try:
        stored = _client().hgetall(_KEY)
        # redis-py types every command as possibly-awaitable; this client is
        # the synchronous one, so the answer is a plain dict.
        stored = cast(dict[str, str], stored)
        # An empty stored value means "back to the default".
        out.update(
            {k: v for k, v in stored.items() if k in _FIELDS and v}
        )
    except Exception:
        logger.warning("runtime settings unavailable — using defaults")
    _cached, _cached_at = out, now
    return out


def set_values(**fields: str) -> dict[str, str]:
    """Store runtime overrides. Empty string clears back to the default."""
    clean = {k: v for k, v in fields.items() if k in _FIELDS}
    if clean:
        _client().hset(_KEY, mapping=clean)
    invalidate()
    return get_all()


def invalidate() -> None:
    """Drop the in-process copy so the next read sees what was just saved."""
    global _cached
    _cached = None
