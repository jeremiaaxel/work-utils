"""Tests for the jp-translator service and HTTP API."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.tools.jp_translator import service


@pytest.fixture
def client(fake_redis, password, monkeypatch):
    """A test client whose translations never reach the network."""
    from app.core import auth

    monkeypatch.setattr(settings.app, "password", "secret")
    monkeypatch.setattr(
        auth,
        "app_write",
        auth.WritePassword("app", lambda: settings.app.password),
    )

    def fake_translate(
        text, target_lang, on_retry=None, max_retries=5, source_lang="auto"
    ):
        return (f"[{target_lang}] {text}", 0, None)

    monkeypatch.setattr(
        "app.tools.jp_translator.service.translate_text", fake_translate
    )

    with TestClient(app) as test_client:
        yield test_client


def test_directions_are_the_fixed_pairs():
    assert service.DIRECTIONS["ja_en"] == ("ja", "en")
    assert service.DIRECTIONS["en_ja"] == ("en", "ja")


async def test_understand_annotates_the_japanese_input(fake_redis, monkeypatch):
    def fake_translate(
        text, target_lang, on_retry=None, max_retries=5, source_lang="auto"
    ):
        return ("English words", 0, None)

    monkeypatch.setattr(
        "app.tools.jp_translator.service.translate_text", fake_translate
    )
    result = await service.translate("日本語を学ぶ", "ja_en")
    # The annotation went to the Japanese input, not the English translation.
    assert "<ruby>" in result["ruby_html"]
    assert result["translation"] == "English words"


async def test_express_annotates_the_japanese_translation(fake_redis, monkeypatch):
    def fake_translate(
        text, target_lang, on_retry=None, max_retries=5, source_lang="auto"
    ):
        return ("日本語です", 0, None)

    monkeypatch.setattr(
        "app.tools.jp_translator.service.translate_text", fake_translate
    )
    result = await service.translate("hello", "en_ja")
    assert "<ruby>" in result["ruby_html"]
    assert result["translation"] == "日本語です"


async def test_kana_only_output_is_not_annotated(fake_redis, monkeypatch):
    def fake_translate(
        text, target_lang, on_retry=None, max_retries=5, source_lang="auto"
    ):
        return ("こんにちは", 0, None)

    monkeypatch.setattr(
        "app.tools.jp_translator.service.translate_text", fake_translate
    )
    result = await service.translate("hello", "en_ja")
    # Kana-only output renders as-is, with no <ruby> tags.
    assert result["ruby_html"] == "こんにちは"
    assert result["reading"] == "こんにちは"


def test_empty_translation_has_no_annotation(fake_redis):
    # A collapsed duplicate returns "" — nothing to annotate, no crash.
    result = service._result("text", "en", "ja", "")
    assert result["ruby_html"] == ""
    assert result["translation"] == ""


def test_api_requires_the_password(client):
    response = client.post(
        "/api/jp-translator/translate",
        json={"text": "こんにちは", "direction": "ja_en"},
    )
    assert response.status_code == 401


def test_api_rejects_a_wrong_password(client):
    response = client.post(
        "/api/jp-translator/translate",
        json={"text": "こんにちは", "direction": "ja_en"},
        headers={"X-App-Password": "wrong"},
    )
    assert response.status_code == 401


def test_api_rejects_an_unknown_direction(client):
    response = client.post(
        "/api/jp-translator/translate",
        json={"text": "こんにちは", "direction": "fr_de"},
        headers={"X-App-Password": "secret"},
    )
    assert response.status_code == 422


def test_api_rejects_too_long_text(client):
    response = client.post(
        "/api/jp-translator/translate",
        json={"text": "あ" * 2001, "direction": "ja_en"},
        headers={"X-App-Password": "secret"},
    )
    assert response.status_code == 422


def test_api_translates_and_annotates(client):
    response = client.post(
        "/api/jp-translator/translate",
        json={"text": "日本語を学ぶ", "direction": "ja_en"},
        headers={"X-App-Password": "secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["translation"].startswith("[en]")
    # The Japanese input is annotated: readings, not surfaces.
    assert "にほんご" in body["reading"]


async def test_a_cached_translation_comes_back_at_once(client, fake_redis):
    client.post(
        "/api/jp-translator/translate",
        json={"text": "テスト", "direction": "ja_en"},
        headers={"X-App-Password": "secret"},
    )
    # A second call hits the cache — assert it is holding the answer, so an
    # offline repeat would still be served.
    from app.core import translation_cache

    cached = await translation_cache.get("en", "テスト")
    assert cached is not None and cached.startswith("[en]")
