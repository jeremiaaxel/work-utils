"""FastHTML pages for jp-translator.

One page, two panels: Understand (ja→en) and Express (en→ja). Each panel is
a Google-translate-style pair — a plain white writing surface on the left,
the translation on the tinted right — and translates itself as you type.
The middle column is a slim divider with a single translate icon, the
recovery path when a request fails.

Japanese renders with ruby furigana on the kanji itself. Copy gives the
plain text; a chevron offers "copy with furigana" in kanji(furigana) form.

translate.js does what JavaScript has to do: the debounced requests, the
copy menu, and the selection-based audio controls.
"""

from fasthtml.common import (
    H1,
    H2,
    Button,
    Div,
    Input,
    Label,
    NotStr,
    P,
    Script,
    Span,
    Style,
    Template,
    Textarea,
)
from fastlucide.icons import Chevron_down, Copy, Play, Refresh_cw, X

from app.fh_app import rt
from app.ui import asset_url, page

_STYLES = """
.jp-japanese {
  line-height: 2.1;
  user-select: text;
  /* The provider answers one line per source line; HTML would fold the
     newlines into spaces without this. */
  white-space: pre-line;
}
.jp-stale { opacity: 0.55; }
.jp-busy::after {
  content: "";
  display: inline-block;
  width: 1em; height: 1em;
  border-radius: 9999px;
  background: currentColor;
  opacity: 0.3;
  margin-top: 0.75em;
  animation: jp-dots 1.2s ease-in-out infinite;
}
@keyframes jp-dots {
  0%, 60%, 100% { transform: scale(0.7); opacity: 0.25; }
  30% { transform: scale(1.15); opacity: 0.55; }
}
/* The writing surface: white like a sheet of paper, no visible field. */
.jp-surface {
  background: var(--color-base-100);
  border-radius: 0.75rem;
  padding: 0.25rem 0.5rem;
}
.jp-surface:focus-within {
  box-shadow: 0 0 0 2px color-mix(in oklab, var(--color-primary) 45%, transparent);
}
.jp-surface textarea {
  border: none;
  box-shadow: none;
  background: transparent;
  resize: none;
  padding: 0.25rem 0.25rem;
}
.jp-surface textarea:focus {
  outline: none;
  box-shadow: none;
}
/* The reading strip under the understand input: quiet, borderless. */
.jp-reading {
  color: color-mix(in oklab, var(--color-base-content) 62%, transparent);
}
.jp-reading rt { font-size: 0.6em; }
/* The translation sheet: slightly tinted, Google's right-hand panel. */
.jp-result-surface {
  background: color-mix(in oklab, var(--color-primary) 6%, var(--color-base-100));
}
/* The slim divider between the two sides. */
.jp-divider { background: var(--color-base-300); width: 1px; }
/* The copy menu revealed by the chevron. */
.jp-copy-menu {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 4px;
  z-index: 20;
  background: var(--color-base-100);
  border: 1px solid var(--color-base-300);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgb(0 0 0 / 0.1);
  min-width: 12rem;
}
.jp-copy-menu button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
}
.jp-copy-menu button:hover { background: var(--color-base-200); }
.jp-copy-menu button + button { border-top: 1px solid var(--color-base-200); }
"""


@rt("/jp-translator/")
def index():
    """The two-way translation page."""
    return page(
        "jp-translator",
        Style(_STYLES),
        H1("JP Translator", cls="text-3xl font-bold mb-2"),
        P(
            "Understand Japanese and express yourself in it — both directions "
            "on one page, with furigana and pronunciation.",
            cls="opacity-70 mb-6",
        ),
        # One password for both panels — translating spends a provider call.
        Label(
            Div(Span("Password", cls="label-text"), cls="label"),
            Input(
                type="password",
                id="jp-password",
                placeholder="required to translate",
                cls="input input-bordered w-full max-w-xs",
            ),
            Div(
                Span(
                    "Needed to translate; kept in this browser",
                    cls="label-text-alt",
                ),
                cls="label",
            ),
            cls="form-control mb-8",
        ),
        Div(
            _panel(
                "understand",
                "Understand",
                "Japanese → English",
                input_label="Japanese",
                result_label="English translation",
                result_lang="en",
                input_lang="ja",
                furigana_under="input",
                input_placeholder="Japanese input…",
                result_placeholder="Translation",
                input_speak="Speak the Japanese input",
                result_speak="Speak the English translation",
            ),
            _panel(
                "express",
                "Express",
                "English → Japanese",
                input_label="English",
                result_label="Japanese translation",
                result_lang="ja",
                input_lang="en",
                furigana_under="result",
                input_placeholder="English input…",
                result_placeholder="Translation",
                input_speak="Speak the English input",
                result_speak="Speak the Japanese translation",
            ),
            cls="flex flex-col gap-10",
        ),
        # One copy menu template, cloned by JavaScript next to whichever
        # copy button opened it.
        Template(
            NotStr(
                "<div class='jp-copy-menu hidden' data-copy-menu>"
                "<button type='button' data-copy-plain>Copy</button>"
                "<button type='button' data-copy-furigana>Copy with "
                "furigana</button>"
                "</div>"
            ),
            id="jp-copy-template",
        ),
        Script(src=asset_url("/jp-translator/translate.js")),
        NotStr("<div id='jp-toast' class='toast toast-end toast-bottom z-50'></div>"),
    )


def _audio_row(panel_id: str, side: str, speak_label: str, with_furigana: bool):
    """One side's audio row: speak, rate, copy (plus a copy menu when the
    side is Japanese and carries furigana)."""
    return Div(
        Button(
            Play(sz=14),
            id=f"jp-{panel_id}-{side}-speak",
            cls="btn btn-ghost btn-xs",
            aria_label=speak_label,
            title=speak_label,
        ),
        Button(
            "1×",
            id=f"jp-{panel_id}-{side}-rate",
            cls="btn btn-ghost btn-xs px-1.5",
            aria_label="Change the playback speed",
            title="Cycle the playback speed",
        ),
        Div(
            Button(
                Copy(sz=13),
                id=f"jp-{panel_id}-{side}-copy",
                cls="btn btn-ghost btn-xs",
                aria_label="Copy",
                title="Copy",
            ),
            *(
                [
                    Button(
                        Chevron_down(sz=12),
                        id=f"jp-{panel_id}-{side}-copy-menu",
                        cls="btn btn-ghost btn-xs px-1",
                        aria_label="More copy options",
                        title="More copy options",
                        aria_expanded="false",
                    )
                ]
                if with_furigana
                else []
            ),
            cls="relative flex items-center",
        ),
        cls="flex items-center gap-1 mt-2",
    )


def _panel(
    panel_id: str,
    title: str,
    direction: str,
    input_label: str,
    result_label: str,
    result_lang: str,
    input_lang: str,
    furigana_under: str,
    input_placeholder: str,
    result_placeholder: str,
    input_speak: str,
    result_speak: str,
):
    """One translation panel: white input left, tinted result right.

    `furigana_under` picks which side is Japanese — the input for
    understand (its reading strip sits under the surface), the result for
    express (ruby renders on the translation itself).
    """
    header = Div(
        H2(
            Span(title, cls="font-bold"),
            Span(f" · {direction}", cls="opacity-70 font-normal"),
            cls="text-xl",
        ),
        cls="flex items-center justify-between mb-3",
    )

    input_side = Div(
        P(input_label, cls="label-text mb-1"),
        Div(
            Textarea(
                id=f"jp-{panel_id}-input",
                cls="w-full min-h-28 leading-relaxed",
                placeholder=input_placeholder,
                rows=4,
                lang=input_lang,
            ),
            Button(
                X(sz=14),
                id=f"jp-{panel_id}-clear",
                cls="btn btn-ghost btn-xs btn-square absolute top-2 right-2 "
                "opacity-40 hover:opacity-100 hidden",
                aria_label="Clear the input",
                title="Clear the input",
            ),
            cls="jp-surface relative",
        ),
        *([_audio_row(panel_id, "input", input_speak, False)]),
        # Understand reads Japanese: the reading strip sits under its input.
        *([_reading_strip(panel_id)] if furigana_under == "input" else []),
        cls="flex-1 min-w-0",
    )
    result_side = Div(
        P(
            result_label,
            Span(
                id=f"jp-{panel_id}-loading",
                cls="loading loading-spinner loading-xs ml-2 align-middle hidden",
                aria_label="Translating",
            ),
            cls="label-text mb-1",
        ),
        Div(
            # Express outputs Japanese: ruby furigana renders on the
            # translation itself — one block, readings on the kanji.
            Div(
                id=f"jp-{panel_id}-result",
                cls="jp-japanese min-h-28 min-w-0 opacity-60",
                lang=result_lang,
                aria_live="polite",
                data_placeholder=result_placeholder,
            ),
            *(
                [
                    _audio_row(
                        panel_id, "result", result_speak, furigana_under == "result"
                    )
                ]
            ),
            # A slightly tinted sheet, Google's right-hand panel.
            cls="jp-result-surface rounded-xl px-4 py-3",
        ),
        cls="flex-1 min-w-0",
    )
    middle = Div(
        Button(
            Refresh_cw(sz=16),
            id=f"jp-{panel_id}-translate",
            cls="btn btn-ghost btn-sm btn-circle",
            aria_label="Translate now",
            title="Translate now",
        ),
        cls="flex items-center justify-center md:self-center",
    )
    return Div(
        header,
        Div(
            input_side,
            Div(cls="jp-divider self-stretch hidden md:block"),
            middle,
            result_side,
            cls="flex flex-col md:flex-row gap-6 md:gap-6 items-stretch",
        ),
        # Errors are announced and live only in their own panel.
        Div(
            id=f"jp-{panel_id}-error",
            role="alert",
            cls="hidden mt-3",
        ),
        cls="p-6 rounded-2xl",
    )


def _reading_strip(panel_id: str):
    """The kana reading of the understand input, filled in by JavaScript."""
    return Div(
        P("Reading", cls="label-text mb-1"),
        Div(id=f"jp-{panel_id}-furigana", cls="jp-reading jp-japanese text-sm"),
        id=f"jp-{panel_id}-furigana-block",
        cls="hidden mt-4",
        lang="ja",
    )
