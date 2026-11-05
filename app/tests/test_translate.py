"""Tests for the translation helper and its providers."""

import pytest

from app.config import settings
from app.core import translate as translate_module
from app.core.translate import _chunk, _clean_translation, translate_text


@pytest.fixture
def providers(monkeypatch):
    """Pin the provider config and reset the circuit breaker."""
    monkeypatch.setattr(settings.translation, "primary", "google")
    monkeypatch.setattr(settings.translation, "fallback", "mymemory")
    monkeypatch.setattr(translate_module, "_blocked_until", {})


def test_dictionary_form_is_cleaned():
    # MyMemory answers short words as "[でんし] /electron/" — the reading is
    # shown separately, so only the meaning is kept.
    assert _clean_translation("[でんし] /electron/electronic/") == "electron/electronic"
    assert _clean_translation("[はどうほうていしき] /wave equation/") == "wave equation"
    assert _clean_translation("Law of Motion") == "Law of Motion"


def test_chunk_keeps_lines_whole():
    text = "first line\nsecond line\nthird line"
    chunks = _chunk(text, 30)
    assert chunks == ["first line\nsecond line", "third line"]


def test_chunk_splits_a_line_that_is_too_long():
    chunks = _chunk("x" * 25, 10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == "x" * 25


def test_chunk_preserves_all_text():
    text = "資本効率と社会的価値を両立させるガバナンス\n自分自身の突破"
    chunks = _chunk(text, 30)
    # Chunks are rejoined with newlines, so nothing is lost.
    assert "\n".join(chunks) == text


def test_the_primary_provider_answers_first(monkeypatch, providers):
    monkeypatch.setitem(translate_module._PROVIDERS, "google", lambda *a: "from google")
    monkeypatch.setitem(
        translate_module._PROVIDERS,
        "mymemory",
        lambda *a: pytest.fail("the fallback should not be called"),
    )
    assert translate_text("力学", "en")[0] == "from google"


def test_the_fallback_answers_when_the_primary_refuses(monkeypatch, providers):
    def boom(*args):
        raise RuntimeError("TooManyRequests")

    monkeypatch.setitem(translate_module._PROVIDERS, "google", boom)
    monkeypatch.setitem(
        translate_module._PROVIDERS, "mymemory", lambda *a: "from fallback"
    )
    assert translate_text("力学", "en")[0] == "from fallback"


def test_a_blocked_primary_is_skipped(monkeypatch, providers):
    monkeypatch.setitem(translate_module._blocked_until, "google", 1e12)
    monkeypatch.setitem(
        translate_module._PROVIDERS,
        "google",
        lambda *a: pytest.fail("a blocked primary should not be called"),
    )
    monkeypatch.setitem(
        translate_module._PROVIDERS, "mymemory", lambda *a: "from fallback"
    )
    assert translate_text("力学", "en")[0] == "from fallback"


def test_a_failed_primary_is_blocked_for_a_while(monkeypatch, providers):
    calls = []

    def refusing(text, target, source):
        calls.append(text)
        raise RuntimeError("TooManyRequests")

    monkeypatch.setitem(translate_module._PROVIDERS, "google", refusing)
    monkeypatch.setitem(
        translate_module._PROVIDERS, "mymemory", lambda *a: "from fallback"
    )
    # max_retries=1 so the refusal blocks immediately; the full ladder would
    # call the primary five times before giving up.
    assert translate_text("力学", "en", max_retries=1)[0] == "from fallback"
    assert translate_text("力学", "en", max_retries=1)[0] == "from fallback"
    assert len(calls) == 1  # the second call went straight to the fallback


def test_an_unknown_primary_falls_back(monkeypatch, providers):
    # A typo in TRANSLATION_PRIMARY degrades to the fallback, loudly logged.
    monkeypatch.setattr(settings.translation, "primary", "gogle")
    monkeypatch.setitem(
        translate_module._PROVIDERS, "mymemory", lambda *a: "from fallback"
    )
    assert translate_text("力学", "en")[0] == "from fallback"


def test_when_every_provider_fails_the_primary_error_is_raised(monkeypatch, providers):
    def boom(*args):
        raise RuntimeError("TooManyRequests")

    monkeypatch.setitem(translate_module._PROVIDERS, "google", boom)
    monkeypatch.setitem(translate_module._PROVIDERS, "mymemory", boom)
    with pytest.raises(RuntimeError, match="TooManyRequests"):
        translate_text("力学", "en")


def test_an_empty_primary_leaves_only_the_fallback(monkeypatch, providers):
    monkeypatch.setattr(settings.translation, "primary", "")
    monkeypatch.setitem(
        translate_module._PROVIDERS, "mymemory", lambda *a: "from fallback"
    )
    assert translate_text("力学", "en")[0] == "from fallback"


def test_an_empty_fallback_leaves_the_primary_error(monkeypatch, providers):
    def boom(*args):
        raise RuntimeError("TooManyRequests")

    monkeypatch.setattr(settings.translation, "fallback", "")
    monkeypatch.setitem(translate_module._PROVIDERS, "google", boom)
    with pytest.raises(RuntimeError, match="TooManyRequests"):
        translate_text("力学", "en")


def test_the_source_reaches_the_primary(monkeypatch, providers):
    calls = []

    def google(text, target, source):
        calls.append((source, target))
        return "ok"

    monkeypatch.setitem(translate_module._PROVIDERS, "google", google)
    translate_text("I study", "ja", source_lang="en")
    assert calls == [("en", "ja")]


def test_retries_call_on_retry(monkeypatch, providers):
    monkeypatch.setattr(translate_module.time, "sleep", lambda seconds: None)
    attempts = []

    def flaky(text, target, source):
        attempts.append(text)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return "recovered"

    monkeypatch.setitem(translate_module._PROVIDERS, "google", flaky)
    seen = []
    result = translate_text(
        "力学", "en", on_retry=lambda *args: seen.append(args), max_retries=3
    )
    assert result[0] == "recovered"
    assert seen == [(1, 3, 2.0, "RuntimeError: boom")]


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _record_langpairs(monkeypatch):
    seen = []

    def fake_get(url, params, timeout):
        seen.append(params["langpair"])
        return _FakeResponse(
            {"responseStatus": 200, "responseData": {"translatedText": "ok"}}
        )

    monkeypatch.setattr(translate_module.httpx, "get", fake_get)
    return seen


def test_the_fallback_assumes_japanese_when_the_source_is_auto(monkeypatch):
    seen = _record_langpairs(monkeypatch)
    translate_module._mymemory_translate("力学", "en", "auto")
    assert seen == ["ja|en"]


def test_the_fallback_uses_the_named_source(monkeypatch):
    seen = _record_langpairs(monkeypatch)
    translate_module._mymemory_translate("I study", "ja", source_lang="en")
    assert seen == ["en|ja"]


def test_mymemory_answers_one_query_per_line(monkeypatch):
    # A translation memory fuzzy-matches the whole query, so one multi-line
    # query returns nonsense ("午前。\n午後." once came back as "12-hour
    # clock"). Each line must be its own query.
    seen = _record_langpairs(monkeypatch)
    translate_module._mymemory_translate("午前。\n午後.", "en", "auto")
    assert seen == ["ja|en", "ja|en"]


def test_deepl_sends_one_field_per_line(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen["url"] = url
        seen["data"] = data or {}
        return _FakeResponse(
            {"translations": [{"text": f"<{t}>"} for t in (data or {}).get("text", [])]}
        )

    monkeypatch.setattr(translate_module.httpx, "post", fake_post)
    monkeypatch.setattr(settings.translation, "deepl_api_key", "fake-key:fx")
    out = translate_module._deepl_translate("午前。\n午後.", "en", "auto")

    # One request, one text field per line, structure reassembled in order.
    assert seen["data"]["text"] == ["午前。", "午後."]
    assert "source_lang" not in seen["data"]  # auto-detect means no source
    assert out == "<午前。>\n<午後.>"
    # A key ending in :fx is a free-tier key and goes to the free host.
    assert "api-free.deepl.com" in seen["url"]


def test_deepl_names_the_source_when_it_has_one(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen["data"] = data or {}
        return _FakeResponse(
            {"translations": [{"text": f"<{t}>"} for t in (data or {}).get("text", [])]}
        )

    monkeypatch.setattr(translate_module.httpx, "post", fake_post)
    monkeypatch.setattr(settings.translation, "deepl_api_key", "fake-key:fx")
    translate_module._deepl_translate("I study", "ja", "en")
    assert seen["data"]["source_lang"] == "EN"


def test_deepl_without_a_key_raises(monkeypatch):
    monkeypatch.setattr(settings.translation, "deepl_api_key", "")
    with pytest.raises(RuntimeError, match="DEEPL_API_KEY"):
        translate_module._deepl_translate("力学", "en", "auto")


def test_lingva_encodes_the_text_into_the_path(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        return _FakeResponse({"translation": "おはよう"})

    monkeypatch.setattr(translate_module.httpx, "get", fake_get)
    monkeypatch.setattr(settings.translation, "lingva_url", "https://lingva.example/")
    out = translate_module._lingva_translate("good morning", "ja", "en")

    assert out == "おはよう"
    # A trailing slash on the URL is tolerated; the text is one path segment.
    assert seen["url"] == "https://lingva.example/api/v1/en/ja/good%20morning"


def test_lingva_without_a_url_raises(monkeypatch):
    monkeypatch.setattr(settings.translation, "lingva_url", "")
    with pytest.raises(RuntimeError, match="LINGVA_URL"):
        translate_module._lingva_translate("力学", "en", "auto")


def test_the_cache_key_names_the_provider(monkeypatch):
    # Entries are keyed per provider, so a poisoned entry from one provider
    # ("12-hour clock") is never served by another, and switching providers
    # starts fresh instead of serving 30 days of the old one's answers.
    from app.core import translation_cache

    key = translation_cache._key("en", "テスト")
    assert key.startswith("tr:en:google:")

    monkeypatch.setattr(settings.translation, "primary", "deepl")
    assert translation_cache._key("en", "テスト") != key
