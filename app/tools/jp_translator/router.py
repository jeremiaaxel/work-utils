"""HTTP layer for the jp-translator tool.

Translating spends a provider call, so it requires the password configured
in ``APP_PASSWORD``. The tool stores nothing — every request is stateless.
"""

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.core.auth import app_write
from app.tools.jp_translator import service
from app.tools.jp_translator.schemas import TranslateRequest

router = APIRouter(prefix="/api/jp-translator", tags=["jp-translator"])


@router.post("/translate")
async def translate(request: Request, payload: TranslateRequest):
    """Translate the text in the requested direction."""
    if len(payload.text) > settings.jp_translator.max_chars:
        raise HTTPException(
            413, f"Text is longer than {settings.jp_translator.max_chars} characters"
        )

    password = request.headers.get("X-App-Password")
    try:
        app_write.require(password)
    except PermissionError as e:
        # Unconfigured gets 503 (a server problem); a wrong password gets 401.
        if "not configured" in str(e):
            raise HTTPException(503, f"{e} on the server")
        raise HTTPException(401, str(e))

    result = await service.translate(payload.text, payload.direction)
    if not result["translation"]:
        # Empty means a duplicate request is already in flight; 409 tells the
        # client to reuse its previous request rather than resend.
        raise HTTPException(409, "The same text is already being translated")
    return result
