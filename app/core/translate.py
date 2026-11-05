"""Shared translation helper.

Providers are named functions in ``_PROVIDERS``, selected by config:
``TRANSLATION_PRIMARY`` answers first; when it refuses (rate limit, outage,
missing key), ``TRANSLATION_FALLBACK`` is tried instead — with a circuit
breaker so a failing primary is not retried on every keystroke.

The registry exists so a provider can be swapped by editing `.env`, not
code: try candidates until one reads well, then make it the default.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx
from deep_translator import GoogleTranslator

from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0

_MYMEMORY_URL = "https://api.mymemory.translated.net/get"
_MYMEMORY_MAX_CHARS = 500
_BLOCK_SECONDS = 300  # skip the primary for this long after it refuses

# MyMemory answers short words in a dictionary form: "[でんし] /electron/".
# The reading is shown separately, so keep only the meaning.
_DICTIONARY_FORM = re.compile(r"^\[[^\]]*\]\s*/(.+?)/?$")


# ── providers ────────────────────────────────────────────────────
# Each takes (text, target_lang, source_lang) and returns the translation.
# "auto" means auto-detect where the provider supports it; MyMemory cannot,
# so there it means Japanese.


def _google_translate(text: str, target_lang: str, source_lang: str) -> str:
    result = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
    return result if result else text


def _deepl_translate(text: str, target_lang: str, source_lang: str) -> str:
    """The official DeepL API. Free keys end with ':fx'.

    The lines go out as separate `text` fields of one request — DeepL answers
    one translation per field, so the line structure comes back intact.
    """
    key = settings.translation.deepl_api_key
    if not key:
        raise RuntimeError("TRANSLATION_DEEPL_API_KEY is not set")
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"

    lines = text.splitlines() or [""]
    non_empty = [i for i, line in enumerate(lines) if line.strip()]
    if not non_empty:
        return text
    data: dict[str, object] = {
        "text": [lines[i] for i in non_empty],
        "target_lang": target_lang.upper(),
    }
    if source_lang != "auto":
        data["source_lang"] = source_lang.upper()
    response = httpx.post(
        f"https://{host}/v2/translate",
        headers={"Authorization": f"DeepL-Auth-Key {key}"},
        data=data,
        timeout=30.0,
    )
    response.raise_for_status()
    translations = response.json().get("translations") or []
    if len(translations) != len(non_empty):
        raise RuntimeError(
            f"DeepL: {len(translations)} translations for {len(non_empty)} lines"
        )
    out = list(lines)
    for i, translation in zip(non_empty, translations):
        out[i] = str(translation.get("text") or "")
    return "\n".join(out)


def _lingva_translate(text: str, target_lang: str, source_lang: str) -> str:
    """A self-hosted Lingva instance — Google's translations without the
    client-side scrape, one hop removed. Needs TRANSLATION_LINGVA_URL."""
    base = settings.translation.lingva_url.rstrip("/")
    if not base:
        raise RuntimeError("TRANSLATION_LINGVA_URL is not set")
    response = httpx.get(
        f"{base}/api/v1/{source_lang}/{target_lang}/{quote(text, safe='')}",
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    if "translation" not in body:
        raise RuntimeError(f"Lingva: {body.get('error') or body}")
    return str(body["translation"])


def _mymemory_translate(text: str, target_lang: str, source_lang: str) -> str:
    """MyMemory, one query per line.

    MyMemory is a translation memory: it fuzzy-matches the whole query, so a
    multi-line query matches nonsense ("午前。\\n午後." once came back as
    "12-hour clock"). Line by line it behaves. Queries are capped at 500
    characters, so a longer line is split.
    """
    source = "ja" if source_lang == "auto" else source_lang
    out: list[str] = []
    for line in text.splitlines() or [""]:
        if not line.strip():
            out.append("")
            continue
        pieces = [
            _mymemory_query(piece, target_lang, source)
            for piece in _chunk(line, _MYMEMORY_MAX_CHARS)
            if piece.strip()
        ]
        out.append("\n".join(pieces))
    return "\n".join(out)


def _mymemory_query(chunk: str, target_lang: str, source_lang: str) -> str:
    response = httpx.get(
        _MYMEMORY_URL,
        params={"q": chunk, "langpair": f"{source_lang}|{target_lang}"},
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("responseStatus") != 200:
        raise RuntimeError(f"MyMemory: {body.get('responseDetails')}")
    return _clean_translation(str(body["responseData"]["translatedText"]))


_PROVIDERS: dict[str, Callable[[str, str, str], str]] = {
    "google": _google_translate,
    "deepl": _deepl_translate,
    "lingva": _lingva_translate,
    "mymemory": _mymemory_translate,
}

# Set per provider when it starts refusing; compared against time.monotonic().
_blocked_until: dict[str, float] = {}


def _run_provider(name: str, text: str, target_lang: str, source_lang: str) -> str:
    try:
        provider = _PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown translation provider {name!r}") from None
    return provider(text, target_lang, source_lang)


def translate_text(
    text: str,
    target_lang: str,
    on_retry: Callable[[int, int, int, str], None] | None = None,
    max_retries: int = MAX_RETRIES,
    source_lang: str = "auto",
) -> tuple[str, int, str | None]:
    """Translate text: the primary provider, then the fallback when it refuses.

    Returns (translated_or_original, retries_used, last_error_msg_or_none).
    `on_retry(attempt, max_retries, wait_s, error_msg)` is called between
    attempts so the caller can surface retry notices to the UI.

    Pass a lower `max_retries` on interactive paths — the full retry ladder
    takes over a minute, which is fine for a background job but not for
    something a user is waiting on.

    `source_lang` defaults to auto-detection. MyMemory cannot detect, so for
    it "auto" means Japanese unless the caller names the source.

    Blocking — call from a thread when running inside an async request handler.
    """
    primary = settings.translation.primary
    primary_error: Exception | None = None
    if primary and time.monotonic() >= _blocked_until.get(primary, 0.0):
        try:
            result = _translate_with_retries(
                primary, text, target_lang, on_retry, max_retries, source_lang
            )
            _blocked_until.pop(primary, None)
            return result
        except Exception as exc:
            primary_error = exc
            logger.warning(
                "%s translate failed (%s); trying the fallback", primary, exc
            )
            _blocked_until[primary] = time.monotonic() + _BLOCK_SECONDS

    fallback = settings.translation.fallback
    if fallback and fallback != primary:
        try:
            return (
                _run_provider(fallback, text, target_lang, source_lang),
                0,
                None,
            )
        except Exception as exc:
            logger.warning("fallback %s failed: %s", fallback, exc)
            primary_error = primary_error or exc

    raise primary_error or RuntimeError("no translation provider available")


def _translate_with_retries(
    provider: str,
    text: str,
    target_lang: str,
    on_retry: Callable[[int, int, int, str], None] | None,
    max_retries: int,
    source_lang: str = "auto",
) -> tuple[str, int, str | None]:
    """Run one provider with capped-exponential-backoff retry."""
    last_err: str | None = None
    for attempt in range(max_retries):
        try:
            return (
                _run_provider(provider, text, target_lang, source_lang),
                attempt,
                last_err,
            )
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt == max_retries - 1:
                raise
            wait = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
            logger.warning(
                "translate retry %d/%d (%s): %s (waiting %ds)",
                attempt + 1,
                max_retries,
                provider,
                last_err,
                wait,
            )
            if on_retry:
                try:
                    on_retry(attempt + 1, max_retries, wait, last_err)
                except Exception:
                    logger.exception("on_retry callback raised")
            time.sleep(wait)
    return text, 0, last_err  # unreachable


def _clean_translation(text: str) -> str:
    """Turn MyMemory's dictionary form into a plain translation."""
    stripped = text.strip()
    match = _DICTIONARY_FORM.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _chunk(text: str, limit: int) -> list[str]:
    """Split text into chunks of at most `limit` characters.

    Lines are kept whole where possible so the translation stays readable.
    """
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > limit:
            # A single line longer than the limit — cut it on character count.
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if not current:
            current = line
        elif len(current) + 1 + len(line) <= limit:
            current = f"{current}\n{line}"
        else:
            chunks.append(current)
            current = line
    if current:
        chunks.append(current)
    return chunks


# The lines of a page are sent as a numbered list, so one request covers the
# whole page and the answers can be split back up.
_NUMBERED_LINE = re.compile(r"^\s*(\d+)[.)]\s*(.*)$")


async def translate_lines(lines: list[str], target_lang: str) -> list[str]:
    """Translate each line of a page.

    One request for the whole page where possible; if the numbering does not
    come back intact, the lines are asked for one by one.
    """
    if not lines:
        return []

    numbered = "\n".join(f"{index + 1}. {line}" for index, line in enumerate(lines))
    try:
        answer, _, _ = await asyncio.to_thread(
            translate_text, numbered, target_lang, None, 2
        )
    except Exception as e:
        logger.warning("the page translation failed: %s: %s", type(e).__name__, e)
        answer = ""

    parsed: dict[int, str] = {}
    for row in answer.splitlines():
        match = _NUMBERED_LINE.match(row)
        if match:
            parsed[int(match.group(1))] = match.group(2).strip()

    if len(parsed) == len(lines):
        return [parsed.get(index + 1, "") for index in range(len(lines))]

    # The numbering did not survive — ask again, line by line.
    out: list[str] = []
    for line in lines:
        try:
            translated, _, _ = await asyncio.to_thread(
                translate_text, line, target_lang, None, 2
            )
        except Exception:
            translated = ""
        out.append(translated)
    return out
