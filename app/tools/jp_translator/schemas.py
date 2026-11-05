"""Request/response models for the jp-translator tool."""

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    """Text to translate, and which way.

    Both panels of the page use this one shape: the direction names the
    fixed language pair, so the client never sends raw language codes.
    """

    text: str = Field(min_length=1, max_length=2000)
    direction: str = Field(pattern="^(ja_en|en_ja)$")
