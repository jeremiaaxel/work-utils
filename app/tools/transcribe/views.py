"""The JP Transcribe page — browser-local speech translation.

Everything confidential happens in the browser: microphone → VAD → whisper
→ opus-mt → kuromoji, all as local model inference. There is deliberately
no API router here (the manifest's Part C forbids server audio endpoints):
the only server role is serving this page and its static JS. The transcript
never reaches the server, so nothing is logged, stored or shareable.

The page makes its privacy claims visible, not just true:

- the readiness card shows model sizes and download progress before Start,
- the recording badge is derived from actual engine state, not static text,
- the connection ledger tallies this page's own outbound requests live,
- the mode banner names what runs where, per the manifest's §5 wording.
"""

from fasthtml.common import (
    H1,
    H2,
    A,
    Button,
    Div,
    NotStr,
    P,
    Script,
    Span,
    Style,
)

from app.fh_app import rt
from app.ui import asset_url, page

_STYLES = """
/* Provisional (still-being-revised) transcript segments read as quieter. */
.tr-provisional { opacity: 0.55; }
/* The recording dot only pulses while getUserMedia is actually live. */
.tr-rec-dot {
  width: 0.75em; height: 0.75em;
  border-radius: 9999px;
  background: var(--color-error);
  animation: tr-pulse 1.2s ease-in-out infinite;
}
.tr-rec-dot[data-live="false"] { animation: none; opacity: 0.3; }
@keyframes tr-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
/* The transcript column scrolls itself only while the reader is at the
   bottom; JS toggles the fade that offers "resume following". */
.tr-follow-fade {
  position: sticky; bottom: 0;
  height: 3rem;
  background: linear-gradient(transparent, var(--color-base-100));
  display: flex; align-items: flex-end; justify-content: center;
  pointer-events: none;
}
.tr-follow-fade button { pointer-events: auto; }
"""


@rt("/transcribe/")
def index():
    """The local transcription + translation page."""
    return page(
        "transcribe",
        Style(_STYLES),
        H1(
        "JP Transcribe",
        Span("beta", cls="badge badge-warning badge-sm align-middle ml-2"),
        cls="text-3xl font-bold mb-2",
    ),
        P(
            "Speech → Japanese text (with furigana) → English, entirely in "
            "this browser. Nothing is sent to the server during a session.",
            cls="opacity-70 mb-2",
        ),
        # Manifest §5 wording. The badge in the toolbar re-derives itself
        # from engine state; this banner states the design up front.
        Div(
            Span("🔒 "),
            Span("Processing: On this device"),
            Span(" · "),
            Span("History: Not saved"),
            Span(
                " — refreshing or closing the tab clears everything.",
                cls="opacity-70",
            ),
            cls="alert alert-success py-2 mb-6 text-sm",
            role="note",
            id="tr-mode-banner",
        ),
        # ── Readiness (manifest §13) ────────────────────────────────
        # Shown before Start; JS replaces it with the toolbar once models
        # are ready. Sizes are the pinned revisions' int8 ONNX files.
        Div(
            H2("Prepare the local models", cls="text-xl font-bold mb-2"),
            P(
                "First run downloads the models into this browser's cache "
                "(about 240 MB total); later runs start from the cache. "
                "Sizes below are what will be fetched, from pinned model "
                "revisions on the Hugging Face CDN.",
                cls="opacity-70 text-sm mb-3",
            ),
            Div(id="tr-model-list", cls="mb-3"),
            Div(
                Button(
                    "Download models & self-test",
                    id="tr-prepare-btn",
                    cls="btn btn-primary",
                ),
                id="tr-prepare-row",
                cls="mb-2",
            ),
            P(
                "The self-test transcribes one short sample locally and "
                "shows the result — Start stays disabled until it passes.",
                cls="opacity-60 text-xs",
            ),
            id="tr-readiness",
            cls="card bg-base-200 p-4 mb-6",
        ),
        # ── Live view ────────────────────────────────────────────────
        # Hidden until readiness passes (CSS class, not JS-hide, so the
        # initial paint is already correct).
        Div(
            # Toolbar: recording state + the privacy badge, both derived
            # from real state by app.js.
            Div(
                Div(
                    Span(cls="tr-rec-dot", id="tr-rec-dot", data_live="false"),
                    Span("Stopped", id="tr-state-text", cls="ml-2 font-semibold"),
                    id="tr-rec-state",
                    cls="flex items-center",
                ),
                Div(
                    Span("⏳ Models not loaded", id="tr-privacy-badge"),
                    cls="badge badge-ghost",
                    id="tr-privacy-wrap",
                ),
                cls="flex flex-wrap items-center justify-between gap-2 mb-3",
            ),
            # Controls (manifest §14): Start/Pause/Stop/Clear. Start appears
            # after readiness; Pause clearly suspends VAD; Stop releases the
            # microphone.
            Div(
                Button("Start", id="tr-start", cls="btn btn-primary", disabled=True),
                Button("Pause", id="tr-pause", cls="btn btn-ghost", disabled=True),
                Button("Stop", id="tr-stop", cls="btn btn-ghost", disabled=True),
                Button(
                    "Clear session", id="tr-clear", cls="btn btn-ghost", disabled=True
                ),
                cls="flex gap-2 mb-4",
            ),
            # The transcript: newest at the bottom, Japanese with furigana
            # above its English translation, provisional segments dimmed.
            Div(
                Div(id="tr-transcript", cls="space-y-3"),
                Div(
                    Button(
                        "↓ Resume following",
                        id="tr-resume-follow",
                        cls="btn btn-xs btn-ghost hidden",
                    ),
                    cls="tr-follow-fade",
                ),
                id="tr-transcript-scroll",
                cls="rounded-box bg-base-200 p-4 h-[50vh] overflow-y-auto",
            ),
            P(
                "Japanese stays selectable; furigana is a toggle. Provisional "
                "(still revising) segments are dimmed until finalized.",
                cls="opacity-60 text-xs mt-2",
            ),
            id="tr-live",
            cls="hidden",
        ),
        # ── Connection ledger (manifest §20 evidence, in-page) ──────
        # Honest scope: this counts what this page can see — its own
        # resource loads. It cannot observe OS-level traffic; the demo
        # package's network capture is the independent verification.
        Div(
            Span("Outbound requests this session: "),
            Span("0", id="tr-ledger-count"),
            Span(" — model assets only. ", cls="opacity-70"),
            A(
                "details",
                href="#tr-ledger-details",
                onclick="document.getElementById('tr-ledger-details')"
                ".classList.toggle('hidden');return false;",
                cls="link link-xs",
            ),
            Div(id="tr-ledger-details", cls="hidden mt-2 text-xs opacity-70"),
            cls="alert py-2 text-sm mb-6",
            id="tr-ledger",
        ),
        # kuromoji is UMD only — load it classically so it sets
        # window.kuromoji; the import map then adapts that global to a
        # module default export.
        Script(
            src="https://cdn.jsdelivr.net/npm/kuromoji@0.1.2/build/kuromoji.js",
        ),
        # Module imports resolve here. transformers.js is pinned ESM from
        # the CDN.
        NotStr(
            "<script type='importmap'>\n"
            "{\n"
            "  \"imports\": {\n"
            "    \"@huggingface/transformers\": "
            "\"https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2"
            "/dist/transformers.min.js\",\n"
            "    \"kuromoji\": \"data:text/javascript,export default "
            "window.kuromoji\"\n"
            "  }\n"
            "}\n"
            "</script>"
        ),
        Script(src=asset_url("/transcribe/app.js"), type="module"),
    )
