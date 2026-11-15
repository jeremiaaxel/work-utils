"""HTTP layer for the settings page.

Reading settings is public (nothing sensitive is returned — the DeepL key
only ever comes back as a boolean). Writing requires the shared app
password, like every other write.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import ocr, runtime_settings
from app.core.auth import app_write

router = APIRouter(prefix="/api/settings", tags=["settings"])

TRANSLATION_PROVIDERS = ("google", "deepl", "lingva", "mymemory")
OCR_ENGINES = ("paddle", "tesseract")


class SettingsUpdate(BaseModel):
    translation_primary: str = ""
    translation_fallback: str = ""
    deepl_api_key: str | None = None  # None = leave unchanged
    lingva_url: str | None = None
    ocr_engine: str = ""


def _require_password(request: Request, supplied: str | None = None) -> None:
    password = request.headers.get("X-App-Password") or supplied
    try:
        app_write.require(password)
    except PermissionError as e:
        if "not configured" in str(e):
            raise HTTPException(503, f"{e} on the server")
        raise HTTPException(401, str(e))


def _public_view(values: dict[str, str]) -> dict:
    """What the page may see — secrets masked to a boolean."""
    return {
        "translation_primary": values["translation_primary"],
        "translation_fallback": values["translation_fallback"],
        "deepl_api_key_set": bool(values["deepl_api_key"]),
        "lingva_url": values["lingva_url"],
        "ocr_engine": values["ocr_engine"],
        "ocr_engines": list(OCR_ENGINES),
        "tesseract_available": ocr.tesseract_available(),
        "providers": list(TRANSLATION_PROVIDERS),
    }


@router.get("")
async def get_settings():
    return _public_view(runtime_settings.get_all())


@router.put("")
async def update_settings(payload: SettingsUpdate, request: Request):
    _require_password(request)

    for name, allowed in (
        ("translation_primary", TRANSLATION_PROVIDERS),
        ("translation_fallback", TRANSLATION_PROVIDERS),
        ("ocr_engine", OCR_ENGINES),
    ):
        value = getattr(payload, name)
        if value and value not in allowed:
            raise HTTPException(400, f"unknown {name}: {value!r}")

    fields: dict[str, str] = {}
    for name in ("translation_primary", "translation_fallback", "ocr_engine"):
        value = getattr(payload, name)
        if value:
            fields[name] = value
    # Secret/URL fields only change when the client sent them at all.
    if payload.deepl_api_key is not None:
        fields["deepl_api_key"] = payload.deepl_api_key.strip()
    if payload.lingva_url is not None:
        fields["lingva_url"] = payload.lingva_url.strip()

    return _public_view(runtime_settings.set_values(**fields))
