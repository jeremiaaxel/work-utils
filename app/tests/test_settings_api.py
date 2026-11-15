"""Tests for the settings API and the runtime-settings store."""

import pytest
from fastapi.testclient import TestClient

from app.core import ocr, runtime_settings
from app.main import app


@pytest.fixture
def client(fake_redis, password):
    with TestClient(app) as test_client:
        yield test_client


def test_get_returns_public_view_without_secrets(client):
    runtime_settings.set_values(
        translation_primary="deepl", deepl_api_key="secret-key:fx"
    )
    data = client.get("/api/settings").json()
    assert data["translation_primary"] == "deepl"
    assert data["deepl_api_key_set"] is True
    assert "secret-key" not in str(data)


def test_put_requires_the_password(client):
    response = client.put(
        "/api/settings", json={"translation_primary": "deepl"}
    )
    assert response.status_code == 401


def test_put_saves_and_survives_a_reload(client):
    response = client.put(
        "/api/settings",
        json={"translation_primary": "deepl", "ocr_engine": "tesseract"},
        headers={"X-App-Password": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["translation_primary"] == "deepl"

    # A fresh process (empty cache) must read the same values.
    runtime_settings.invalidate()
    values = runtime_settings.get_all()
    assert values["translation_primary"] == "deepl"
    assert values["ocr_engine"] == "tesseract"


def test_put_rejects_an_unknown_provider(client):
    response = client.put(
        "/api/settings",
        json={"translation_primary": "chatgpt"},
        headers={"X-App-Password": "secret"},
    )
    assert response.status_code == 400


def test_put_rejects_an_unknown_engine(client):
    response = client.put(
        "/api/settings",
        json={"ocr_engine": "hal"},
        headers={"X-App-Password": "secret"},
    )
    assert response.status_code == 400


def test_omitted_secret_fields_are_kept(client):
    runtime_settings.set_values(deepl_api_key="keep-me:fx")
    client.put(
        "/api/settings",
        json={"translation_primary": "deepl"},
        headers={"X-App-Password": "secret"},
    )
    assert runtime_settings.get_all()["deepl_api_key"] == "keep-me:fx"


def test_an_explicit_empty_string_clears_a_secret(client):
    runtime_settings.set_values(deepl_api_key="keep-me:fx")
    client.put(
        "/api/settings",
        json={"deepl_api_key": ""},
        headers={"X-App-Password": "secret"},
    )
    assert runtime_settings.get_all()["deepl_api_key"] == ""


def test_ocr_engine_selection_validated_against_the_registry():
    from app.core.ocr import selected_engine

    runtime_settings.set_values(ocr_engine="paddle")
    assert selected_engine() == "paddle"
    runtime_settings.set_values(ocr_engine="nonsense")
    assert selected_engine() == "paddle"


def test_tesseract_availability_is_reported(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_available", lambda: False)
    from app.tools.settings.router import _public_view

    view = _public_view(runtime_settings.get_all())
    assert view["tesseract_available"] is False
    assert "tesseract" in view["ocr_engines"]
