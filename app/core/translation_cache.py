"""Shared cache of phrase translations, keyed by language and text.

Any tool that translates user-typed phrases uses this so the same text is
not sent to the provider twice. Lives in Redis database 4, under ``tr:``,
next to jp-reader's own ``jr:`` keys.

Storage failures degrade to a cache miss — they must never break a request.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    import redis.asyncio as _redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_DB = 4
_PREFIX = "tr:"
_TTL = int(timedelta(days=30).total_seconds())

logger = logging.getLogger(__name__)


def _key(lang: str, text: str) -> str:
    """Key includes the provider, so switching providers starts fresh.

    Entries from before this key existed (provider-less `tr:<lang>:<hash>`)
    simply stop being asked for — a poisoned entry ("12-hour clock" for
    `午前。\\n午後.`) needs no migration, just abandonment.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{_PREFIX}{lang}:{settings.translation.primary}:{digest}"


async def _get_redis() -> _redis.Redis:
    """Lazy-init the Redis connection."""
    import redis.asyncio as _redis_mod

    if not hasattr(_get_redis, "_client"):
        _get_redis._client = _redis_mod.from_url(  # type: ignore[attr-defined]
            f"{REDIS_URL}/{_DB}"
        )
    return _get_redis._client  # type: ignore[attr-defined]


async def get(lang: str, text: str) -> str | None:
    """A previously stored translation, or None. Never raises."""
    try:
        r = await _get_redis()
        cached = await r.get(_key(lang, text))
        return cached.decode() if isinstance(cached, bytes) else cached
    except Exception:
        logger.warning("translation cache read failed", exc_info=True)
        return None


async def put(lang: str, text: str, translation: str) -> None:
    """Remember a translation for the TTL. Never raises."""
    try:
        r = await _get_redis()
        await r.setex(_key(lang, text), _TTL, translation)
    except Exception:
        logger.warning("translation cache write failed", exc_info=True)
