"""Pure logic for the jp-translator tool.

No FastAPI imports: this module is testable without an HTTP server.

Both panels of the page come through here — understand (ja→en) and express
(en→ja). A translation spends a provider call, so results are cached and the
same text is never sent twice while one is already in flight.
"""

import asyncio

from app.core import translation_cache
from app.core.japanese import to_plain_reading, to_ruby_html, tokenize_with_reading
from app.core.translate import translate_text

# The user is waiting for this one, so do not sit through the full retry
# ladder — same reasoning as jp-reader's PREVIEW_RETRIES.
TRANSLATE_RETRIES = 2

# Text being translated right now, so the same one is not sent twice.
_inflight: set[str] = set()


# Directions are fixed pairs; the manifest pins them so the UI cannot
# accidentally swap languages.
DIRECTIONS: dict[str, tuple[str, str]] = {
    "ja_en": ("ja", "en"),
    "en_ja": ("en", "ja"),
}


async def translate(text: str, direction: str) -> dict:
    """Translate `text` in `direction`, annotating the Japanese side.

    Returns {"translation", "ruby_html", "reading"} — ruby_html carries the
    furigana of whichever text is Japanese: the input for ja→en (the panel
    shows the input with furigana), the translation for en→ja.
    """
    source, target = DIRECTIONS[direction]
    cached = await translation_cache.get(target, text)
    if cached is not None:
        return _result(text, source, target, cached)

    key = f"{direction}:{text}"
    if key in _inflight:
        # Another identical request is already running; let it finish rather
        # than queueing a duplicate provider call behind it.
        return _result(text, source, target, "")
    _inflight.add(key)
    try:
        translation, _, _ = await asyncio.to_thread(
            translate_text, text, target, None, TRANSLATE_RETRIES, source
        )
        await translation_cache.put(target, text, translation)
        return _result(text, source, target, translation)
    finally:
        _inflight.discard(key)


def _result(text: str, source: str, target: str, translation: str) -> dict:
    """The response body — annotate whichever side of the pair is Japanese."""
    out = {"translation": translation, "ruby_html": "", "reading": ""}
    ja_text = text if source == "ja" else translation
    if ja_text:
        tokens = tokenize_with_reading(ja_text)
        out["ruby_html"] = to_ruby_html(tokens)
        out["reading"] = to_plain_reading(tokens)
    return out
