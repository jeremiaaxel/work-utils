"""FastHTML page for the runtime settings.

A single form: translation providers (primary, fallback, credentials) and
the OCR engine. Rendered server-side; settings.js only does the fetches.
"""

from fasthtml.common import (
    H1,
    H2,
    Button,
    Div,
    Input,
    Label,
    NotStr,
    Option,
    P,
    Script,
    Select,
    Span,
)
from fastlucide.icons import Save

from app.fh_app import rt
from app.ui import asset_url, page


@rt("/settings/")
def index():
    return page(
        "settings",
        H1("Settings", cls="text-3xl font-bold mb-2"),
        P(
            "Which services do the work. Saved here applies to new jobs "
            "within a few seconds — no restart needed. Settings are kept "
            "in Redis: they survive restarts, but if the Redis data is "
            "ever lost they fall back to the .env defaults.",
            cls="opacity-70 mb-6",
        ),
        Div(
            Div(
                H2("Translation", cls="text-lg font-bold mb-3"),
                Div(
                    _select(
                        "translation_primary",
                        "Primary",
                        "Answers first; falls back when it refuses",
                    ),
                    _select(
                        "translation_fallback",
                        "Fallback",
                        "Takes over when the primary is down or rate-limited",
                    ),
                    _secret(
                        "deepl_api_key",
                        "DeepL API key",
                        "Free keys end with “:fx”",
                    ),
                    _text(
                        "lingva_url",
                        "Lingva instance URL",
                        "e.g. https://lingva.example.com",
                    ),
                    cls="space-y-4",
                ),
                cls="card-body",
            ),
            cls="card bg-base-200 shadow-xl",
        ),
        Div(
            Div(
                H2("OCR engine", cls="text-lg font-bold mb-3"),
                Div(
                    Label(
                        Div(Span("Engine", cls="label-text"), cls="label"),
                        Select(
                            Option("PaddleOCR — best accuracy", value="paddle"),
                            Option("Tesseract — self-hosted", value="tesseract"),
                            id="set-ocr_engine",
                            cls="select select-bordered w-full max-w-xs",
                        ),
                        Div(
                            Span(
                                "Tesseract keeps pages on this server — use it "
                                "for confidential files. It needs tesseract-ocr "
                                "and its Japanese models installed.",
                                cls="label-text-alt",
                            ),
                            id="set-ocr-hint",
                            cls="label",
                        ),
                        cls="form-control",
                    ),
                    cls="space-y-4",
                ),
                cls="card-body",
            ),
            cls="card bg-base-200 shadow-xl mt-6",
        ),
        Div(
            Div(
                Label(
                    Input(
                        type="password",
                        id="set-password",
                        placeholder="app password (needed to save)",
                        cls="input input-bordered w-full max-w-xs",
                    ),
                    cls="form-control",
                ),
                Button(
                    Save(sz=16),
                    "Save",
                    type="button",
                    id="set-save",
                    cls="btn btn-primary gap-2",
                ),
                Span(id="set-status", cls="text-sm opacity-70"),
                cls="card-body flex flex-row items-end gap-4",
            ),
            cls="card bg-base-200 shadow-xl mt-6",
        ),
        Script(src=asset_url("/settings.js")),
        NotStr("<div id='set-toast' class='toast toast-end toast-bottom z-50'></div>"),
    )


def _select(field: str, label: str, help_text: str):
    options = "".join(
        f"<option value='{p}'>{p}</option>"
        for p in ("google", "deepl", "lingva", "mymemory")
    )
    return Label(
        Div(Span(label, cls="label-text"), cls="label"),
        NotStr(
            f"<select id='set-{field}' class='select select-bordered "
            f"w-full max-w-xs'>{options}</select>"
        ),
        Div(Span(help_text, cls="label-text-alt"), cls="label"),
        cls="form-control",
    )


def _text(field: str, label: str, placeholder: str):
    return Label(
        Div(Span(label, cls="label-text"), cls="label"),
        Input(
            type="text",
            id=f"set-{field}",
            placeholder=placeholder,
            cls="input input-bordered w-full max-w-xs",
        ),
        cls="form-control",
    )


def _secret(field: str, label: str, help_text: str):
    return Label(
        Div(
            Span(label, cls="label-text"),
            Span(
                id=f"set-{field}-state",
                cls="badge badge-ghost badge-sm ml-2 hidden",
            ),
            cls="label",
        ),
        Input(
            type="password",
            id=f"set-{field}",
            placeholder=help_text,
            cls="input input-bordered w-full max-w-xs",
        ),
        Div(
            Span(
                "Leave blank to keep the current value",
                cls="label-text-alt",
            ),
            cls="label",
        ),
        cls="form-control",
    )
