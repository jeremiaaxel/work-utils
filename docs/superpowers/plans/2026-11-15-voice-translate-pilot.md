# Voice Translate Pilot — near-real-time ja→en speech translation

> **STATUS: SUPERSEDED IN PART** — the `jp-transcribe` manifest (repo root)
> requires **browser-local** inference and forbids server audio endpoints
> (Part C). The engine/transport choices below (server-side whisper,
> segment POST) are overridden; the privacy section stands. Full rewrite
> pending.
> Primary direction: Japanese → English. Fits the existing work-utils stack
> (FastAPI + FastHTML + Redis + TaskIQ, single VPS behind Caddy).

---

## Goal

Hold a conversation with a Japanese speaker: you speak Japanese, the screen
shows the English translation ~1–2 s after you stop talking, and can read it
aloud. One shared screen (phone or laptop). Pilot scope is ja→en with a
direction toggle; two-sided live conversation polish comes later.

## Shape of the pipeline

Four stages; three of them reuse code the app already has:

```
browser                          web (FastAPI)                worker (unchanged)
┌─────────────────────────┐
│ getUserMedia +          │  POST /api/voice/segments
│ AudioWorklet 16 kHz ────┼───────────────────────────▶  ┌──────────────┐
│ VAD → utterance segment │  service.py:                 │ PaddleOCR    │
│ render transcript pairs │   core/stt.py  → text (ja)   │ (untouched)  │
│ speechSynthesis (en) ◀──┼─  core/translate.py → en     └──────────────┘
└─────────────────────────┘   reuse translation_cache
```

- **Capture + VAD in the browser.** AudioWorklet taps 16 kHz mono PCM;
  silero-VAD (wasm, CDN, no build step — same as HTMX/Tailwind today)
  detects end-of-utterance with a ~350 ms hangover and cuts a segment.
- **STT is the only genuinely new backend capability.** Everything else —
  translation providers, runtime settings, auth, page shell — exists.
- **Transport for the pilot is ordinary HTTP**: one POST per utterance
  segment carrying a small WAV. No WebSocket infra in pilot; the service
  layer is transport-agnostic so a streaming WS can replace the edge later
  without touching STT/translation.

## Options considered

### STT engine (the load-bearing choice)

| Engine | Latency | ja quality | Cost | Infra impact |
|---|---|---|---|---|
| **faster-whisper small int8, local** ← pilot pick | ~0.6–1.5 s / utterance | good (conversational) | free | +~500 MB RAM in web container, model downloaded once to a volume |
| vosk ja (local, true streaming) | ~0.3 s streaming | fair | free | tiny model, but meaningfully worse ja accuracy |
| OpenAI whisper API (batch per segment) | ~1–2 s | very good | $0.006/min | needs keys; fits runtime_settings provider pattern |
| Google Cloud STT streaming | ~0.5 s + partials | excellent | $/min | keys + gRPC/WS client; best end state |
| Browser Web Speech API | ~0.5 s | varies | free | zero backend, but Chrome-leaning, unofficial, uncontrollable — OK for a throwaway spike, not the product |

Pilot pick rationale: zero new keys or per-minute cost, reuses the exact
pattern established for OCR (registry in `core/`, heavy deps isolated, model
warm-up like `app/warmup.py`), and accuracy is pilot-adequate. The registry
makes cloud providers a later drop-in.

### Transport

| Transport | Latency | Complexity | Pilot verdict |
|---|---|---|---|
| **Segmented HTTP POST** ← pilot pick | segment + ~1–2 s processing | none — plain request/response, idempotent, trivially testable | yes |
| WebSocket PCM stream | lowest; enables partials + barge-in | new connection lifecycle, reconnects, Caddy/proxy considerations | P2 |
| WebRTC | lowest for P2P; media-server complexity for no P2P benefit here | high | no |

### Where STT runs

| Where | Latency | Complexity | Pilot verdict |
|---|---|---|---|
| **Inline in web process** (`asyncio.to_thread`) ← pilot pick | lowest | none — no queue round-trip; personal-scale load (1–2 users) | yes |
| TaskIQ worker with result backend | +50–200 ms | needs a result backend config the app doesn't have today | P1 move if CPU contention appears |

RAM is additive either way (same model, one container or the other); the web
image grows by ctranslate2 (~200 MB wheel) — acceptable for a personal tool,
and the `ocr` group precedent exists if we later want it out.

## Latency budget (pilot)

| Stage | Time |
|---|---|
| VAD endpoint (silero, 350 ms hangover) | ~0.4 s after last syllable |
| WAV encode + POST (3–5 s segment ≈ 100–200 KB) | ~0.05–0.1 s |
| faster-whisper small int8, 4 s utterance, 4 vCPU | ~0.6–1.5 s |
| translate.py provider (google/deepl) | ~0.2–0.4 s |
| render + TTS start | ~0.05 s |
| **Total** | **~1.3–2.4 s** |

## Plan

### P0 — pilot (one tool, four files + core module)

Follows the standard "Adding a tool" checklist:

- `app/core/stt.py` — engine registry (`whisper-local` default; fixture/null
  engine for tests), lazy singleton model load, `language` param.
- `app/tools/voice/` — `router.py` (`POST /api/voice/segments`, auth-gated),
  `views.py` (the page: big mic button, scrolling ja/en transcript pairs, TTS
  toggle), `service.py` (segment → STT → translate → pair), `schemas.py`.
- `app/static/voice/` — AudioWorklet + VAD + WAV-encoder JS (CDN silero).
- Wire-up: `main.py` router, `ui.py` page registry, `views.py` home card.
- pyproject: add `faster-whisper` (default group, like ocr; web runs it in
  pilot). Model downloaded at startup to a persisted volume; add RAM note to
  `docs/deployment.md`.
- Settings: `stt_engine` + whisper model size via `runtime_settings._FIELDS`.
- Tests: registry, segment endpoint (canned WAV through a fixture engine),
  service e2e with mocked STT — no model download in CI.
- UI: reuse `ui-ux-pro-max` when building the page.

### P1 — conversation quality

Direction toggle en→ja (symmetric already: whisper language param +
translation direction + TTS voice). Shareable session transcript via the
`jr_store`-style filesystem+Redis pattern. Whisper medium as a
runtime-settings option. VAD tuning (silero thresholds, min/max segment).

### P2 — streaming

WebSocket edge replacing segment POST (same service layer): partial
hypotheses, barge-in (duck/pause TTS when the mic hears speech), cloud
streaming STT providers behind the same registry.

## Risks

- **Whisper ja accuracy** on noisy/conversational input — the main quality
  risk; mitigated by silero VAD, model-size setting, cloud drop-in path.
- **CPU contention** with the PaddleOCR worker if OCR and voice run
  simultaneously on a small VPS — separate containers already; add CPU
  limits / swap note if it bites.
- **Echo/feedback**: TTS output re-captured by the mic → mute VAD while TTS
  is speaking; note headphones.
- **Mobile Safari**: getUserMedia/AudioWorklet/speechSynthesis need HTTPS
  (Caddy TLS ✓) and a user gesture (start button ✓); test on iOS early.
- **A 500 MB model download** on first deploy — do it in warm-up, not first
  utterance; volume-mounted so restarts don't re-download.

## Confidentiality: make it local, then *prove* it on-screen

The `jp-transcribe` manifest sets hard constraints the pilot design above
violates: inference must be **browser-local** (Part B §12–14), no server
audio endpoints, WebSockets, or server models (Part C §16), no silent cloud
fallback, session-only content, and a demonstration package that shows the
claims are true (Part D §20). Revised design:

**Engine path (replaces server-side faster-whisper):** whisper in the
browser. Select one tested path, not several:

| Path | Runtime | ja quality | Cost | Notes |
|---|---|---|---|---|
| **transformers.js / ONNX Runtime Web + whisper-tiny/small (ONNX)** ← pick | WASM/WebGPU | usable (tiny) → good (small) | free, Apache/MIT models | pure JS, no native build, works CPU-only; WebGPU accelerates where present |
| whisper.cpp → WASM (e.g. `@xenova/whisper.cpp` style bindings) | WASM/SIMD | good | free | heavier integration, no WebGPU; strong CPU path |
| Web Speech API | browser-internal | varies | free | **rejected**: Chrome's implementation calls Google servers — not local, unverifiable |

CPU fallback is mandatory (manifest §12: report limitations, don't silently
go remote); WebGPU is an accelerator, not a requirement.

**Local translation:** the manifest's `Translator` interface needs a
browser-local ja→en model — evaluate a small NMT (e.g. Opus-MT ja-en via
transformers.js, ~80 MB) against quality requirements; if quality fails,
report the limitation rather than falling back to `core/translate.py`
(which is a remote provider — that's the "no silent cloud fallback" line).

**Furigana:** the server's pykakasi path is off-limits in local mode (it
would send text). Evaluate kuromoji.js + a kana converter, or include
readings via the local model tokenizer where feasible. Furigana must never
block transcription display (§15).

**Interface seam (§17):** browser-side `Transcriber` / `Translator` /
`ReadingAnnotator` objects with `initialize() / transcribe() / translate() /
dispose()` — stable segment IDs, provisional vs final results, so a future
remote backend could emit the same events. Session orchestration stays
separate from model implementation. No WS, no server worker changes in this
build; Part C stays documentation-only.

**Trust UX — show, don't just claim:** privacy that the user can't see might
as well not exist, so make the confidentiality state a first-class UI
element, backed by evidence:

- **Processing badge, always visible while recording** — a persistent
  status chip: `⏺ On this device — audio & text never leave this browser`,
  green while local-ready, amber/grey when models aren't loaded. It must be
  derivable from actual state (models initialized, VAD running), not a
  static string — a lie in a badge is worse than no badge.
- **Mode banner distinguishes what's real:** `Processing: On this device /
  Processing: Remote translation provider` (§5 wording) — if the
  translation step uses the server registry, say remote; never label remote
  processing as local.
- **Pre-flight readiness card** (§13): before Start, show model names +
  sizes, download progress, then the distinction *Downloaded → Cached →
  In memory → Ready*, plus a **Test mic & inference** step that runs one
  round-trip locally and displays the result before enabling Start.
- **Network evidence, in-page:** a DevTools-free "connection ledger" —
  during a session the page itself tallies its own outbound requests
  (via PerformanceObserver on resource entries, own-origin only) and shows
  `Outbound requests this session: N — model assets only` with a drill-down
  of asset URLs. Honest scope: the page can't see OS-level traffic, so the
  copy says *this page made N requests, none carrying audio or transcript
  text* — which the code review + §20 network capture (Wireshark/
  browser devtools HAR in the demo package) independently verify.
- **Recording indicator:** the explicit Start/Stop plus a visible
  red recording dot while the mic is open (getUserMedia active), and Pause
  that visibly suspends VAD. TTS/pronunciation playback stays off by
  default (§15).
- **Session-only by construction:** transcript lives in JS memory; Clear
  session wipes it; refresh loses it (state that in the UI once, §4.5).
  Nothing about the transcript goes to Redis, the jr_store, logs, or URLs —
  the server never sees it, so there's nothing to persist.

**Honesty discipline:** every claim maps to an artifact — badge ↔ engine
state; ledger ↔ PerformanceObserver + HAR capture in the demo package;
"On this device" ↔ verified network capture (§20). The demo package also
needs the offline test (airplane mode after init → transcription still
works), storage inspection (no transcript in IndexedDB/localStorage), and
log inspection. Disclose the real limits: delivered JS is trusted code,
extensions/device compromise out of scope, model quality varies (§21).

**What this changes in the plan:** P0 becomes browser-local — no
`app/core/stt.py`, no `/api/voice/segments`, no faster-whisper dep; the web
container only serves static JS + model assets (self-host models where
feasible, CSP-restricted, §19). P1 carries the JP Translate privacy work
(Part A: session-only defaults, explicit encrypted save) and the evidence
package. Server-side whisper is demoted to the documented future mode
(Part C §18) — implemented only as an explicit, warned, non-default
selection, never a fallback.

## Decision record

- Modular monolith maintained (per team-size/iteration matrix): voice is a
  tool directory + one core module, no new deployable unit.
- HTTP-over-WS for pilot: transport is an edge concern; service layer stays
  transport-agnostic so P2 is additive.
- Local STT before cloud: no keys, no cost, reuses established patterns;
  registry preserves the cloud upgrade path.
