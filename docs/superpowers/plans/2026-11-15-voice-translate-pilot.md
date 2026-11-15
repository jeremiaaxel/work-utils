# Voice Translate Pilot — near-real-time ja→en speech translation

> **STATUS: DRAFT** — brainstorm / pilot design. Inspired by PocketTalk web.
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

## Decision record

- Modular monolith maintained (per team-size/iteration matrix): voice is a
  tool directory + one core module, no new deployable unit.
- HTTP-over-WS for pilot: transport is an edge concern; service layer stays
  transport-agnostic so P2 is additive.
- Local STT before cloud: no keys, no cost, reuses established patterns;
  registry preserves the cloud upgrade path.
