# JP Transcribe — inspection report + implementation decisions (manifest §3)

> **STATUS: COMPLETE** — initial deliverable per manifest §3: actual files to
> change, selected approaches, brief tradeoffs, unresolved questions.
> Companion to the implementation manifest (`jp-transcribe`, repo root).

## §3.1 — Repository inspection findings

**Frontend framework / routes / styling**
- Server-rendered FastHTML (`app/fh_app.py` shared instance, `rt` decorator).
  Pages: `app/tools/<tool>/views.py` build FT trees; interactivity lives in
  plain vanilla JS per tool under `app/static/<tool>/` (no bundler, no npm).
  Styling: Tailwind + DaisyUI from CDN, referenced in `app/ui.py` page shell.
  Icon library: `fastlucide` (server side).
- Route registration is side-effect imports in `app/main.py` (views) + APIRouters.

**Current translation provider and request paths**
- `app/core/translate.py` — provider registry (google/deepl/lingva/mymemory)
  run **server-side** in `asyncio.to_thread`, selected via runtime settings
  (Redis, 2 s cache) with `.env` bootstrap defaults.
- jp_translator flow: browser `fetch(API + "/translate", POST {text,
  direction})` → `router.py` → `service.py` → provider + Redis phrase cache.
  Fallback chain retries across providers; failures logged as warnings
  (`logger.warning("fallback %s failed")`) — **messages, not text** (verified:
  no log call receives `payload.text`; only type names).

**Where text appears in URLs / logs / storage / analytics**
- **URLs: YES — jp_translator.** `app/static/jp-translator/translate.js:25–39`
  mirrors both panel inputs into `?ja=…&en=…` via `replaceState` (shareable,
  Google-style). Manifest §6 requires removing this. jp_reader uses opaque
  record IDs — compliant already.
- **Logs: no content.** Access logging is uvicorn default (paths only, no
  query-string echoing of POST bodies; text travels in bodies). App logs
  carry no translation text (grep-verified above).
- **Storage: `localStorage` holds only** `app-password` (all tools) and the
  jp-reader show-translated toggle + theme. No translation content persisted.
  No IndexedDB anywhere. No service worker. No analytics.
- **Third-party scripts:** Tailwind CDN, DaisyUI CDN, HTMX, Google Fonts (via
  `app/ui.py`), plus model CDNs if we fetch from HF at runtime (see below).
  These fire on every page load today — relevant to the §19 isolation and
  CSP discussion.

**Auth**
- `app/core/auth.py`: shared `APP_PASSWORD`, `X-App-Password` header, writes
  only; reads open. Password cached in `localStorage["app-password"]` by each
  tool's JS. Digest comparison (timing-safe). Fine for LAN tool.

**Furigana**
- `app/core/japanese.py`: janome tokenization + pykakasi readings,
  server-side, returned as `ruby_html`. Browser-local equivalent needed for
  Transcribe (see decision below).

**Tests**
- `app/tests/` — service + API level, `fakeredis` via `fake_redis` fixture;
  no browser tests. Transcribe adds a first browser-heavy feature; Python
  tests will cover what little server code exists (mostly the page shell and
  any asset routes), with manual verification per manifest §23.

## §3.2 — Browser inference capability assessment

**Target browser/OS** (user's fleet: Linux laptop + Android phone; iOS Safari
unconfirmed): Firefox and Chromium on desktop; Chrome on Android. WebGPU:
Chromium yes (behind flag on some builds), Firefox rolling out; **CPU/WASM
path is the mandatory baseline** (manifest §12: report limitations, never
fall back remotely).

**WebGPU availability:** accelerates whisper-tiny/base and opus-mt decode
where present; code must feature-detect and run WASM/SIMD otherwise. Expect
roughly: whisper-tiny int8 WASM ≈ real-time-ish on desktop CPU (4× slower
than WebGPU), WebGPU ≈ 2–4× faster.

**Model inventory (verified live from Hugging Face, 2026-11-15):**

| Model | int8 ONNX size (enc+dec) | License | ja quality |
|---|---|---|---|
| `onnx-community/whisper-tiny` | ~50 MB | apache-2.0 (OpenAI Whisper code; model card untagged — verify before pin) | fair for clear speech |
| `onnx-community/whisper-base` | ~85 MB | apache-2.0 | better; the sweet spot |
| `Xenova/whisper-small` | ~250 MB (merged int8) | apache-2.0 | good; desktop-only RAM/latency |
| `Xenova/opus-mt-ja-en` | ~120 MB (enc+dec int8) | apache-2.0 (base `Helsinki-NLP/opus-mt-ja-en`) | decent phrase-level; domain-limited |
| silero-vad (via transformers.js) | ~2 MB | MIT | good VAD |
| kuromoji.js + dictionary | ~17 MB dict (gzipped less) | MIT | readings via token dict |

Full kit (whisper-base + opus-mt + kuromoji + VAD) ≈ **220–240 MB** first
download; cached in the browser Cache API afterwards (application/model
assets only — content never cached, §13.3).

**RAM:** whisper-base WASM ≈ 400–700 MB peak on CPU; opus-mt adds ~200 MB.
Desktop fine; mid-range phones borderline — the readiness card must report
device-appropriate defaults and whisper-tiny as the phone option.

**Offline behavior:** after models are cached, inference runs with network
offline (Cache API serves the assets). Verified by the §23 offline test.

## Files to change (decided)

**New — `app/tools/transcribe/`**
- `views.py` — `/transcribe/` page: readiness card (model sizes, progress,
  Downloaded→Cached→In-memory→Ready), mic test step, then the live view
  (ja with furigana + en, provisional in grey, final in black, red recording
  dot, privacy badge, connection ledger, Start/Pause/Stop/Clear).
- `router.py` — **none for audio** (manifest §16 forbids server audio
  endpoints). Only the page route; no API router at all in local mode.
- `schemas.py` — n/a (no API). Omit file; note in docstring why.
- `service.py` — n/a in local mode. Omit.
- `static/transcribe/` (new dir): `app.js` (orchestrator: state machine,
  segment IDs, provisional/final), `vad.js` (silero via transformers.js),
  `asr.js` (whisper pipeline wrapper: init/dispose/transcribe),
  `mt.js` (opus-mt wrapper), `furigana.js` (kuromoji wrapper),
  `ledger.js` (PerformanceObserver outbound-request tally),
  `workers/asr-worker.js` (AudioWorklet + inference worker off main thread).

**Changed**
- `app/main.py` — import transcribe views.
- `app/ui.py` — page registry entry.
- `app/views.py` — home card.
- `app/static/jp-translator/translate.js` — **remove URL mirroring** (§6;
  Part A step 2 of the order in §24).
- `pyproject.toml` — no new Python deps (browser-only). Models served from
  **CDN pinned by commit hash** initially (HF resolve URLs with `?download=
  true` pinned revisions); self-hosting later if CSP tightening requires.

**Part A (JP Translate privacy) in the same series:** remove URL state
(above), add `Processing: Remote translation provider / History: Not saved`
banner to jp_translator views, session-only confirmation, Clear session
button. Explicit encrypted IndexedDB save (§7) is its own follow-up PR —
flagged, not in the transcribe pilot.

## Tradeoffs (brief, per §3)

1. **transformers.js vs whisper.cpp-WASM** — transformers.js wins: no native
   build, VAD+ASR+MT in one runtime, WebGPU support, pinned model revisions.
   whisper.cpp has better CPU throughput but three separate integrations.
2. **opus-mt-ja-en vs server translate** — local required by §16/§11; quality
   is the known limitation to measure (§23 benchmark). No silent fallback.
3. **CDN models vs self-host** — CDN first (no repo bloat, revision-pinned);
   self-host when the CSP story hardens (§19 self-host requirement, feasible
   follow-up: download to `app/static/models/`, gitignore + warm-up script).
4. **kuromoji vs server pykakasi** — server call would leak text; local only.

## Unresolved questions (for the user)

1. **Target device for the first benchmark**: Linux desktop (Chromium/Firefox)
   confirmed, or is the phone the priority? Determines whisper-base vs tiny
   default.
2. **iOS in scope?** Safari WASM works but WebGPU/SIMD paths and iOS speech
   quirks (mediaSession, muted-tab throttling) need a device test day.
3. **Part A encrypted save** — separate PR after Transcribe MVP, or same
   series? Manifest order (§24) puts it before Transcribe; my reading: URL
   removal + disclosure banner now, encrypted save as its own PR.
4. **Model hosting**: CDN-pinned acceptable for the pilot (implies HF is a
   visible third party in the ledger), or self-host from day one?
