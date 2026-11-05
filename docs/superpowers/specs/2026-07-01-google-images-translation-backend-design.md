# Google Images Translation Backend — Design

**Status:** draft  
**Date:** 2026-07-01  
**Goal:** Add an optional translation backend using Google Translate's image translation feature (via headless Playwright) alongside the existing Tesseract pipeline. Users select which backend to use per-task via the UI.

---

## Motivation

The current Tesseract-based in-place translation has three fundamental quality issues:

1. **Contextless translation** — each OCR line hits Google Translate independently. A sentence split across 3 lines becomes 3 isolated translations, producing word salad.
2. **White-box destruction** — `draw.rectangle(fill="white")` obliterates backgrounds, gradients, and diagram elements behind text.
3. **Font collapse** — Japanese→English text is 30-50% longer than the original region width, so the auto-sizing font shrinks to sub-8px.

Google Translate's built-in Images tab handles OCR, translation, and layout-preserving rendering as a single pipeline — producing significantly better results. The Playwright-based backend automates this tab.

---

## Architecture

```
User selects backend per-task:
  [Tesseract (local)] or [Google Images (cloud)]

         │
         ▼

app/tools/image_translator/backends/
├── __init__.py          # TranslationBackend protocol + get_backend()
├── tesseract.py         # Current pipeline, extracted (no logic changes)
└── google_images.py     # Playwright-based backend (new)

app/tools/image_translator/service.py  # delegates to selected backend
app/tools/image_translator/router.py   # passes backend param through
app/tasks/translate.py                 # passes backend param to service
```

### Backend protocol

```python
class TranslationBackend(Protocol):
    async def translate(
        self, image_paths, target_lang, output_dir, *,
        cache_base=None, cache_key="", force=False, font_path=None,
        on_progress=None, on_log=None,
    ) -> dict:  # {"paths": [...], "elapsed": float, "cache_hit": bool}
        ...
```

Both backends return identical output — the caller (service, router, wizard) is unchanged.

### Selection

- `TRANSLATION_BACKEND` env var sets the default in the UI dropdown
- User can override per-task via `<select name="backend">` in the form
- Template receives `default_backend` from `settings.translation.backend`

---

## Google Images Backend — per-page flow

```
Session setup (once):
  ┌─ launch Chromium (headless)
  ├─ apply playwright-stealth (fingerprint obfuscation)
  ├─ pick random viewport from pool
  ├─ rotate User-Agent
  └─ create persistent browser context (cookies survive across pages)

Per-page loop:
  ┌── 1. Navigate to translate.google.com/?sl=auto&tl={target}&op=images
  ├── 2. Upload image via hidden <input type="file">
  ├── 3. Wait for translation to complete (poll result <img> src)
  ├── 4. Download result image (data: URL, blob: URL, or CDN fetch)
  ├── 5. Save to output_dir/page-NN.jpg
  └── 6. random.uniform(3, 8) seconds delay
```

### Step 3 — waiting for translation

```
- Locate the result container element
- Poll every 500ms: does the result <img> have a non-empty, non-placeholder src?
- Success: src is a data: URL or blob: URL with translated image
- Timeout: 60s per page → skip page, continue with remaining
```

### Step 4 — downloading the result

```python
src = await result_img.get_attribute("src")
if src.startswith("data:"):
    # Decode base64 data URL → bytes → save
    content = base64.b64decode(src.split(",", 1)[1])
elif src.startswith("blob:"):
    # Evaluate in page: fetch blob → ArrayBuffer → bytes → save
    buffer = await page.evaluate("""async (url) => {
        const r = await fetch(url);
        const buf = await r.arrayBuffer();
        return Array.from(new Uint8Array(buf));
    }""", src)
    content = bytes(buffer)
else:
    # CDN URL → fetch with page cookies → save
    cookies = await context.cookies()
    content = await httpx.get(src, cookies=...)
```

---

## Anti-detection measures

| Measure | Implementation |
|---|---|
| **Fingerprint** | `playwright-stealth` — hides `navigator.webdriver`, fakes plugins, fakes WebGL vendor |
| **Viewport** | Pick from pool: `[1920x1080, 1536x864, 1440x900, 1366x768]` each session |
| **Delays** | `random.uniform(3, 8)` between pages. Human-like typing delays (50-150ms) if text input needed |
| **Cookies** | Single persistent `BrowserContext` per session — looks like one user translating multiple images |
| **User-Agent** | Rotate from pool of recent Chrome stable versions |
| **Session rotation** | New browser context every 20 pages (mimics closing/reopening browser tab) |

---

## Error handling

| Scenario | Behavior |
|---|---|
| **Captcha/block** | Retry up to 2× with new browser context + fresh fingerprint. If still blocked, fail with: "Google blocked the request. Try again later or switch to Tesseract." |
| **Page timeout (60s)** | Log warning, skip that page, continue with remaining. Mark skipped in progress. |
| **Playwright crash** | Auto-restart browser, continue from last completed page. |
| **Result image empty** | Retry single page up to 3×, then skip. |
| **Rate limiting (page 50+)** | Auto-insert longer delays: `random.uniform(8, 15)` after page 50. |

---

## Configuration

```bash
# .env — sets default in UI dropdown
TRANSLATION_BACKEND=tesseract

# Google Images backend only:
GOOGLE_TRANSLATE_TIMEOUT=60            # max seconds per page
GOOGLE_TRANSLATE_DELAY_MIN=3           # min seconds between pages
GOOGLE_TRANSLATE_DELAY_MAX=8           # max seconds between pages
GOOGLE_TRANSLATE_MAX_PAGES=100         # safety cap (refuse if exceeded)
```

```python
# app/config.py — new section
class TranslationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRANSLATION_", **_ENV)
    target_lang: str = "en"
    backend: str = "tesseract"    # NEW
```

---

## Files to create

```
app/tools/image_translator/backends/__init__.py
app/tools/image_translator/backends/tesseract.py
app/tools/image_translator/backends/google_images.py
```

## Files to modify

```
app/tools/image_translator/service.py    # delegate to backend
app/tools/image_translator/router.py     # pass backend from form
app/tools/wizard/router.py               # pass backend from form
app/tasks/translate.py                   # pass backend to service
app/templates/tools/image_translator.html # add backend dropdown
app/templates/tools/wizard.html          # add backend dropdown
app/config.py                            # add backend field
.env.example                             # add TRANSLATION_BACKEND
Dockerfile                               # + playwright + chromium deps
pyproject.toml                           # + playwright, playwright-stealth
```

## Files unchanged

```
app/core/progress.py
app/core/task_manager.py
app/brokers/taskiq_broker.py
app/tools/image_translator/schemas.py
app/tools/wizard/schemas.py
docker-compose.yml
```

---

## Testing

- **Unit**: `tesseract.py` extraction — verify identical output before/after refactor
- **Unit**: `google_images.py` — mock Playwright, verify image upload/download/save flow
- **Integration**: Start app with `TRANSLATION_BACKEND=google-images`, upload a single test image, verify translated output exists
- **Smoke**: Both backends produce valid JPEG files in `output_dir`
- **Edge case**: 50-page document with `google-images` backend — verify delays increase after page 50, no blocks

## Rollout

1. Extract Tesseract into `backends/tesseract.py` — zero behavior change, verify
2. Add protocol + `get_backend()` dispatch
3. Add UI dropdown (hidden if only one backend? No — always visible, default from env)
4. Add `google_images.py` with Playwright
5. Add Docker deps
6. End-to-end test both backends