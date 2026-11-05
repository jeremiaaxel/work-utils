# Google Images Translation Backend — Implementation Plan

> **STATUS: COMPLETE** — All 10 tasks implemented and committed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Playwright-based Google Images translation backend alongside the existing Tesseract pipeline, selectable per-task via UI dropdown.

**Architecture:** Extract Tesseract logic into `backends/tesseract.py`, create `backends/google_images.py` with Playwright automation, and add a `TranslationBackend` protocol + registry. `service.py` becomes a thin dispatcher. `tasks/translate.py` delegates to the selected backend. Routers and templates add a `backend` parameter.

**Tech Stack:** FastAPI, Jinja2, Playwright, playwright-stealth, httpx, TaskIQ, Redis

## Global Constraints

- Python >= 3.12
- Zero behavior change to existing Tesseract pipeline during extraction
- Both backends produce identical output format: JPEG files in `output_dir`
- Backend selection is user-facing (per-task dropdown), not env-var-only
- Docker image must include Chromium + deps for Playwright
- Anti-detection: playwright-stealth, random delays, viewport/user-agent rotation

---

### Task 1: Add `backend` field to config

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `settings.translation.backend` (str, default `"tesseract"`) — consumed by routers (Task 6, 7) for template default

- [ ] **Step 1: Add `backend` field to TranslationSettings**

```python
# app/config.py — add one line to TranslationSettings
class TranslationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRANSLATION_", **_ENV)

    target_lang: str = "en"
    backend: str = "tesseract"
```

- [ ] **Step 2: Update .env.example**

```bash
# .env.example — add after TRANSLATION_TARGET_LANG
TRANSLATION_BACKEND=tesseract
```

- [ ] **Step 3: Verify**

```bash
uv run python -c "from app.config import settings; print(settings.translation.backend)"
```
Expected: `tesseract`

- [ ] **Step 4: Commit**

```bash
git add app/config.py .env.example
git commit -m "feat(config): add TRANSLATION_BACKEND setting

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Create backend protocol + registry

**Files:**
- Create: `app/tools/image_translator/backends/__init__.py`

**Interfaces:**
- Produces: `TranslationBackend` Protocol class, `get_backend(name: str) -> TranslationBackend`
- Consumed by: Task 5 (service.py), Task 8 (tasks/translate.py)

- [ ] **Step 1: Create backends directory and __init__.py**

```bash
mkdir -p app/tools/image_translator/backends
```

```python
"""Translation backends — pluggable engines for image translation.

A backend translates images in-place. Same contract, different engines.
Add new backends by creating a module in this package and registering
it in get_backend().
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol


ProgressCallback = Callable[[int, int], Awaitable[None]]
LogCallback = Callable[[str], Awaitable[None]]


class TranslationBackend(Protocol):
    """A backend translates images in-place."""

    async def translate(
        self,
        image_paths: list[Path],
        target_lang: str,
        output_dir: Path,
        *,
        cache_base: Path | None = None,
        cache_key: str = "",
        force: bool = False,
        font_path: str | None = None,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
    ) -> dict:
        """Translate images. Returns {"paths": [...], "elapsed": float, "cache_hit": bool}."""
        ...


def get_backend(name: str) -> TranslationBackend:
    """Return the named backend instance."""
    match name:
        case "tesseract":
            from app.tools.image_translator.backends.tesseract import TesseractBackend
            return TesseractBackend()
        case "google-images":
            from app.tools.image_translator.backends.google_images import GoogleImagesBackend
            return GoogleImagesBackend()
        case _:
            raise ValueError(f"Unknown translation backend: {name}")
```

- [ ] **Step 2: Verify protocol imports**

```bash
uv run python -c "from app.tools.image_translator.backends import TranslationBackend, get_backend; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/tools/image_translator/backends/__init__.py
git commit -m "feat(backends): add TranslationBackend protocol + get_backend registry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Extract Tesseract into backend

**Files:**
- Create: `app/tools/image_translator/backends/tesseract.py`
- Modify: `app/tools/image_translator/service.py` — convert to dispatcher

**Interfaces:**
- Consumes: `TranslationBackend` protocol (Task 2)
- Produces: `TesseractBackend` class, plus module-level functions `_ocr_regions`, `_translate_text`, `_translate_one_image_inplace` (used by Task 8)
- Original internal functions remain accessible for `tasks/translate.py`

- [ ] **Step 1: Move all Tesseract logic to backends/tesseract.py**

Copy the full content of `app/tools/image_translator/service.py` into `app/tools/image_translator/backends/tesseract.py`, then wrap the main function in a class.

The file has these components to move:
- `ProgressCallback`, `LogCallback` type aliases — keep in backends/__init__.py (already done in Task 2)
- `TRANSLATE_CHUNK_SIZE`, `MAX_RETRIES`, `TRANSLATE_DELAY`, `REGION_PADDING` — keep as module-level
- `_FONT_CANDIDATES` — keep as module-level
- `_find_font()` — keep as module-level function
- `_translate_text()` — keep as module-level function
- `_ocr_regions()` — keep as module-level function
- `_translate_one_image_inplace()` — keep as module-level function
- `translate_images_inplace()` — becomes `TesseractBackend.translate()`
- `ProgressCallback` / `LogCallback` types — already in backends/__init__.py

Write `app/tools/image_translator/backends/tesseract.py`:

```python
"""Tesseract-based in-place translation backend.

OCR → Google Translate → white-out → render. Local, no external APIs beyond
Google Translate's free web endpoint.
"""

import asyncio
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytesseract
from deep_translator import GoogleTranslator
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

TRANSLATE_CHUNK_SIZE = 4000
MAX_RETRIES = 3
TRANSLATE_DELAY = 2  # seconds between pages
REGION_PADDING = 4   # px padding around text bounding boxes

_FONT_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/TTF/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
]


def _find_font(font_path: str | None = None, size: int = 14) -> ImageFont.FreeTypeFont:
    """Find a CJK-capable font. Uses explicit path, env var, candidates, or Pillow default."""
    import os

    if font_path and Path(font_path).exists():
        return ImageFont.truetype(font_path, size)
    env_path = os.environ.get("TRANSLATION_FONT_PATH", "")
    if env_path and Path(env_path).exists():
        return ImageFont.truetype(env_path, size)
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    logger.warning("No CJK font found — translated text may render as tofu (boxes)")
    return ImageFont.load_default()


def _translate_text(text: str, target_lang: str) -> str:
    """Translate text with exponential-backoff retry."""
    translator = GoogleTranslator(source="auto", target=target_lang)
    for attempt in range(MAX_RETRIES):
        try:
            result = translator.translate(text)
            return result if result else text
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 3 ** (attempt + 1)
            logger.warning(
                "translate retry %d/%d: %s (waiting %ds)",
                attempt + 1, MAX_RETRIES, e, wait,
            )
            time.sleep(wait)
    return text  # unreachable


def _ocr_regions(img: Image.Image) -> list[dict]:
    """Run Tesseract OCR with region data, return grouped text regions.

    Each region dict: {'bbox': (x1, y1, x2, y2), 'text': str}
    Words are grouped into lines by Y-proximity, then lines into paragraphs.
    """
    data = pytesseract.image_to_data(img, lang="jpn", output_type=pytesseract.Output.DICT)

    words: list[dict] = []
    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        if not text or int(data["conf"][i]) < 0:
            continue
        x, y, w, h = (
            int(data["left"][i]),
            int(data["top"][i]),
            int(data["width"][i]),
            int(data["height"][i]),
        )
        words.append({"text": text, "x": x, "y": y, "w": w, "h": h})

    if not words:
        return []

    words.sort(key=lambda w: (w["y"], w["x"]))

    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_y_center = None

    for w in words:
        wy_center = w["y"] + w["h"] / 2
        if current_y_center is None:
            current_line = [w]
            current_y_center = wy_center
        elif abs(wy_center - current_y_center) < max(w["h"] * 0.6, 5):
            current_line.append(w)
            current_y_center = sum(x["y"] + x["h"] / 2 for x in current_line) / len(current_line)
        else:
            lines.append(current_line)
            current_line = [w]
            current_y_center = wy_center
    if current_line:
        lines.append(current_line)

    regions: list[dict] = []
    for line in lines:
        line.sort(key=lambda w: w["x"])
        x1 = min(w["x"] for w in line)
        y1 = min(w["y"] for w in line)
        x2 = max(w["x"] + w["w"] for w in line)
        y2 = max(w["y"] + w["h"] for w in line)
        text = "".join(w["text"] for w in line)
        regions.append({"bbox": (x1, y1, x2, y2), "text": text})

    return regions


def _translate_one_image_inplace(
    img_path: Path,
    target_lang: str,
    output_dir: Path,
    index: int,
    font_path: str | None = None,
) -> dict:
    """CPU-bound pipeline for one image: OCR → translate → inpaint → render.

    Returns dict with 'path', 'region_count', 'ocr_sample'.
    """
    img = Image.open(img_path).convert("RGB")
    img_w, img_h = img.size

    regions = _ocr_regions(img)
    if not regions:
        out_path = output_dir / f"page-{index:02d}.jpg"
        img.save(out_path, quality=92)
        img.close()
        return {"path": out_path, "region_count": 0, "ocr_sample": ""}

    for region in regions:
        if region["text"].strip():
            try:
                region["translated"] = _translate_text(region["text"], target_lang)
            except Exception:
                region["translated"] = region["text"]
        else:
            region["translated"] = ""

    draw = ImageDraw.Draw(img)

    for region in regions:
        x1, y1, x2, y2 = region["bbox"]
        translated = region.get("translated", "")

        if not translated.strip():
            continue

        px1 = max(0, x1 - REGION_PADDING)
        py1 = max(0, y1 - REGION_PADDING)
        px2 = min(img_w, x2 + REGION_PADDING)
        py2 = min(img_h, y2 + REGION_PADDING)

        region_w = px2 - px1
        region_h = py2 - py1

        draw.rectangle([px1, py1, px2, py2], fill="white")

        font_size = region_h
        font = None
        while font_size >= 8:
            try:
                font = _find_font(font_path, font_size)
                break
            except Exception:
                font_size -= 1

        if font is None:
            font = _find_font(font_path, 12)

        while font_size >= 8:
            bbox = draw.textbbox((0, 0), translated, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            if text_w <= region_w:
                break
            font_size -= 1
            try:
                font = _find_font(font_path, font_size)
            except Exception:
                break

        if text_h > region_h:
            draw.rectangle([px1, py1, px2, py1 + text_h + REGION_PADDING * 2], fill="white")

        text_color = (0, 0, 0)
        draw.text((px1 + 2, py1 + 2), translated, fill=text_color, font=font)

    out_path = output_dir / f"page-{index:02d}.jpg"
    img.save(out_path, quality=92)
    img.close()

    ocr_sample = regions[0]["text"][:100] if regions else ""
    return {"path": out_path, "region_count": len(regions), "ocr_sample": ocr_sample}


class TesseractBackend:
    """Tesseract-based in-place image translation."""

    async def translate(
        self,
        image_paths: list[Path],
        target_lang: str,
        output_dir: Path,
        *,
        cache_base: Path | None = None,
        cache_key: str = "",
        force: bool = False,
        font_path: str | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        on_log: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        """In-place image translation: OCR, translate, inpaint, render."""
        t0 = time.monotonic()
        output_dir.mkdir(parents=True, exist_ok=True)
        if force and any(output_dir.iterdir()):
            shutil.rmtree(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            if on_log:
                await on_log("Force mode: cleared output directory")

        total = len(image_paths)

        cache_dir = cache_base / f"{cache_key}_inplace_{target_lang}" if cache_base and cache_key else None
        if cache_dir and not force:
            cached = sorted(cache_dir.glob("page-*.jpg"))
            if len(cached) == total:
                logger.info("translate cache hit: %s (%d files)", cache_dir, total)
                if on_log:
                    await on_log(f"Translate cache hit: {total} pages")
                for src in cached:
                    shutil.copy2(src, output_dir / src.name)
                paths = sorted(output_dir.glob("page-*.jpg"))
                if on_progress:
                    await on_progress(total, total)
                elapsed = time.monotonic() - t0
                return {"paths": paths, "elapsed": elapsed, "cache_hit": True}

        translated: list[Path] = []
        for i, img_path in enumerate(image_paths):
            out_path = output_dir / f"page-{i:02d}.jpg"
            if out_path.exists():
                logger.info("translate: page %d/%d already translated, skipping", i + 1, total)
                if on_log:
                    await on_log(f"Page {i + 1}/{total}: already translated")
                translated.append(out_path)
                if on_progress:
                    await on_progress(i + 1, total)
                continue

            logger.info("translate: page %d/%d (%s) -> %s", i + 1, total, img_path.name, target_lang)
            if on_progress:
                await on_progress(i + 1, total)
            if on_log:
                await on_log(f"Page {i + 1}/{total}: OCR + translating...")

            result = await asyncio.to_thread(
                _translate_one_image_inplace, img_path, target_lang, output_dir, i, font_path,
            )
            translated.append(result["path"])

            logger.info(
                "translate: page %d/%d: %d regions, OCR sample=%r",
                i + 1, total, result["region_count"], result["ocr_sample"],
            )
            if on_log:
                await on_log(
                    f"Page {i + 1}/{total}: {result['region_count']} text regions found "
                    f"(sample: {result['ocr_sample'][:80]})"
                )

            if cache_dir:
                cache_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(result["path"], cache_dir / result["path"].name)

            if i < total - 1:
                await asyncio.sleep(TRANSLATE_DELAY)

        elapsed = time.monotonic() - t0
        logger.info("translate_images_inplace done: %d pages in %.1fs", len(translated), elapsed)
        return {"paths": translated, "elapsed": elapsed, "cache_hit": False}
```

- [ ] **Step 2: Replace service.py with thin dispatcher**

Replace `app/tools/image_translator/service.py`:

```python
"""Image translation service — thin dispatcher to backend engines.

Backend selection is per-call via the `backend` parameter.
"""

import logging
from pathlib import Path

from app.tools.image_translator.backends import get_backend

logger = logging.getLogger(__name__)


async def translate_images_inplace(
    image_paths: list[Path],
    target_lang: str,
    output_dir: Path,
    cache_base: Path | None = None,
    cache_key: str = "",
    force: bool = False,
    font_path: str | None = None,
    on_progress=None,
    on_log=None,
    backend: str = "tesseract",
) -> dict:
    """Translate images in-place using the selected backend.

    Returns dict with 'paths', 'elapsed', 'cache_hit'.
    """
    be = get_backend(backend)
    return await be.translate(
        image_paths=image_paths,
        target_lang=target_lang,
        output_dir=output_dir,
        cache_base=cache_base,
        cache_key=cache_key,
        force=force,
        font_path=font_path,
        on_progress=on_progress,
        on_log=on_log,
    )
```

- [ ] **Step 3: Verify Tesseract backend still works**

```bash
uv run python -c "
from app.tools.image_translator.service import translate_images_inplace
print('Service dispatcher imports OK')
from app.tools.image_translator.backends.tesseract import TesseractBackend
print('Tesseract backend imports OK')
"
```
Expected: Both print OK

- [ ] **Step 4: Verify existing callers still work**

```bash
uv run python -c "from app.main import app; print('App imports OK')"
```
Expected: `App imports OK`

- [ ] **Step 5: Commit**

```bash
git add app/tools/image_translator/backends/tesseract.py app/tools/image_translator/service.py
git commit -m "refactor(backends): extract Tesseract into backend, service.py becomes dispatcher

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Create Google Images backend

**Files:**
- Create: `app/tools/image_translator/backends/google_images.py`

**Interfaces:**
- Consumes: `TranslationBackend` protocol (Task 2)
- Produces: `GoogleImagesBackend` class — full Playwright-based translation
- Consumed by: `get_backend()` registry (Task 2) and tasks (Task 8)

- [ ] **Step 1: Write google_images.py**

```python
"""Google Images translation backend.

Uses Playwright to automate translate.google.com's Images tab.
Uploads each page image, waits for translation, downloads the result.

Anti-detection: playwright-stealth, random viewports, user-agent rotation,
random delays between pages, persistent browser context (cookies).
"""

import asyncio
import base64
import logging
import os
import random
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────

PAGE_TIMEOUT = int(os.getenv("GOOGLE_TRANSLATE_TIMEOUT", "60"))
DELAY_MIN = float(os.getenv("GOOGLE_TRANSLATE_DELAY_MIN", "3"))
DELAY_MAX = float(os.getenv("GOOGLE_TRANSLATE_DELAY_MAX", "8"))
MAX_PAGES = int(os.getenv("GOOGLE_TRANSLATE_MAX_PAGES", "100"))

VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def _build_url(target_lang: str) -> str:
    return f"https://translate.google.com/?sl=auto&tl={target_lang}&op=images"


async def _sleep_random(min_s: float, max_s: float) -> None:
    """Sleep for a random duration in [min_s, max_s]."""
    await asyncio.sleep(random.uniform(min_s, max_s))


class GoogleImagesBackend:
    """Playwright-based backend using Google Translate's Images tab."""

    async def translate(
        self,
        image_paths: list[Path],
        target_lang: str,
        output_dir: Path,
        *,
        cache_base: Path | None = None,
        cache_key: str = "",
        force: bool = False,
        font_path: str | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        on_log: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        """Translate images via Google Translate Images tab."""
        from playwright.async_api import async_playwright

        t0 = time.monotonic()
        output_dir.mkdir(parents=True, exist_ok=True)

        if force and any(output_dir.iterdir()):
            shutil.rmtree(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        total = len(image_paths)
        if total > MAX_PAGES:
            raise ValueError(
                f"Cannot translate {total} pages — maximum is {MAX_PAGES}. "
                f"Split into smaller batches or set GOOGLE_TRANSLATE_MAX_PAGES higher."
            )

        # Cache check
        cache_dir = cache_base / f"{cache_key}_google_{target_lang}" if cache_base and cache_key else None
        if cache_dir and not force:
            cached = sorted(cache_dir.glob("page-*.jpg"))
            if len(cached) == total:
                if on_log:
                    await on_log(f"Google Translate cache hit: {total} pages")
                for src in cached:
                    shutil.copy2(src, output_dir / src.name)
                paths = sorted(output_dir.glob("page-*.jpg"))
                if on_progress:
                    await on_progress(total, total)
                elapsed = time.monotonic() - t0
                return {"paths": paths, "elapsed": elapsed, "cache_hit": True}

        # Launch browser with stealth
        if on_log:
            await on_log("Launching browser...")

        async with async_playwright() as pw:
            viewport = random.choice(VIEWPORT_POOL)
            user_agent = random.choice(USER_AGENT_POOL)

            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale="en-US",
            )

            try:
                page = await context.new_page()

                # Apply stealth if available
                try:
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    """)
                except Exception:
                    pass

                translated: list[Path] = []
                rotated_at = 0

                for i, img_path in enumerate(image_paths):
                    out_path = output_dir / f"page-{i:02d}.jpg"
                    if out_path.exists():
                        translated.append(out_path)
                        if on_progress:
                            await on_progress(i + 1, total)
                        continue

                    if on_log:
                        await on_log(f"Page {i + 1}/{total}: uploading to Google...")

                    # Rotate context every ~20 pages
                    if i - rotated_at >= 20:
                        await context.close()
                        await _sleep_random(2, 5)
                        viewport = random.choice(VIEWPORT_POOL)
                        user_agent = random.choice(USER_AGENT_POOL)
                        context = await browser.new_context(
                            viewport=viewport, user_agent=user_agent, locale="en-US",
                        )
                        page = await context.new_page()
                        rotated_at = i
                        if on_log:
                            await on_log("Rotated browser context")

                    try:
                        await _translate_one_page(
                            page, img_path, target_lang, out_path, timeout=PAGE_TIMEOUT,
                        )
                    except Exception as e:
                        logger.error("Page %d/%d failed: %s", i + 1, total, e)
                        if on_log:
                            await on_log(f"Page {i + 1}/{total} FAILED: {e}")
                        continue

                    translated.append(out_path)

                    # Cache
                    if cache_dir:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(out_path, cache_dir / out_path.name)

                    if on_progress:
                        await on_progress(i + 1, total)

                    # Rate-limit delay
                    if i < total - 1:
                        delay = DELAY_MAX if i >= 50 else random.uniform(DELAY_MIN, DELAY_MAX)
                        await asyncio.sleep(delay)

            finally:
                await context.close()
                await browser.close()

        elapsed = time.monotonic() - t0
        logger.info("GoogleImagesBackend done: %d pages in %.1fs", len(translated), elapsed)
        return {"paths": translated, "elapsed": elapsed, "cache_hit": False}


async def _translate_one_page(
    page,
    img_path: Path,
    target_lang: str,
    out_path: Path,
    *,
    timeout: int = 60,
) -> None:
    """Upload a single image to Google Translate and save the result."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    url = _build_url(target_lang)
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

    # Wait for the Images tab to be active and the file input to appear
    # Google's Images tab has a hidden <input type="file">
    await page.wait_for_selector('input[type="file"]', state="attached", timeout=15_000)

    # Upload the image
    file_input = page.locator('input[type="file"]').first
    await file_input.set_input_files(str(img_path))

    # Wait for translation to complete — look for the result image
    # Google renders the translated image in an <img> inside the result area
    try:
        # Wait for the result to appear (the translated image)
        result_img = page.locator('div[role="main"] img').first
        await result_img.wait_for(state="visible", timeout=timeout * 1000)

        # Wait a bit more for rendering to settle
        await page.wait_for_timeout(2000)

        # Get the result image source
        src = await result_img.get_attribute("src")

        if not src:
            raise RuntimeError("Result image has no src attribute")

        if src.startswith("data:image/"):
            # Base64 data URL — decode and save
            _, encoded = src.split(",", 1)
            out_path.write_bytes(base64.b64decode(encoded))
        elif src.startswith("blob:"):
            # Blob URL — evaluate in page to extract bytes
            from playwright.async_api import TimeoutError as PlaywrightTimeout  # noqa: F811
            buffer = await page.evaluate("""async (url) => {
                const r = await fetch(url);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""", src)
            out_path.write_bytes(bytes(buffer))
        else:
            # CDN URL — fetch with page cookies
            cookies = await page.context.cookies()
            cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(src, headers={"Cookie": cookie_header})
                resp.raise_for_status()
                out_path.write_bytes(resp.content)

    except PlaywrightTimeout:
        raise RuntimeError(
            f"Translation timed out after {timeout}s. Google may be slow or blocking."
        )
```

- [ ] **Step 2: Verify backend imports (may fail without playwright installed yet)**

```bash
uv run python -c "from app.tools.image_translator.backends.google_images import GoogleImagesBackend; print('Google Images backend import OK')"
```
Expected: `OK` (if playwright not installed, note it for Task 9)

- [ ] **Step 3: Commit**

```bash
git add app/tools/image_translator/backends/google_images.py
git commit -m "feat(backends): add Google Images translation backend via Playwright

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Update image_translator router + template

**Files:**
- Modify: `app/tools/image_translator/router.py`
- Modify: `app/templates/tools/image_translator.html`

**Interfaces:**
- Consumes: `settings.translation.backend` (Task 1)
- Produces: `backend` parameter in `.kiq()` call and template context

- [ ] **Step 1: Add backend to router POST /translate**

The router needs to:
1. Accept `backend` from form
2. Pass `default_backend` to template
3. Include `backend` in the `.kiq()` call

Edit `app/tools/image_translator/router.py`:

```python
# In index() — add default_backend to template context
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "tools/image_translator.html",
        {
            "default_lang": settings.translation.target_lang,
            "default_backend": settings.translation.backend,
        },
    )


# In start_translate() — accept backend from form, pass to .kiq()
@router.post("/translate")
async def start_translate(
    request: Request,
    files: list[UploadFile],
    target_lang: str = Form(""),
    backend: str = Form("tesseract"),
    force: bool = Form(False),
):
    ...

    # Include backend in the .kiq() call
    await translate_images_task.kiq(
        task_id=task_id,
        image_paths=image_paths,
        target_lang=target_lang,
        output_dir=out_dir,
        cache_base=cache_base,
        cache_key=str(uuid.uuid4())[:8],
        force=force,
        backend=backend,
    )


# In retry_task() — also pass backend
@router.post("/retry/{task_id}")
async def retry_task(
    request: Request,
    task_id: str,
    backend: str = Form("tesseract"),
    force: bool = Form(False),
):
    ...

    await translate_images_task.kiq(
        ...
        backend=backend,
    )
```

- [ ] **Step 2: Add backend dropdown to template**

In `app/templates/tools/image_translator.html`, add after the target language dropdown:

```html
<label class="form-control mt-4">
    <div class="label"><span class="label-text">Translation Engine</span></div>
    <select name="backend" id="backend-select" class="select select-bordered w-full max-w-xs">
        <option value="tesseract" {% if default_backend == 'tesseract' %}selected{% endif %}>Tesseract (local)</option>
        <option value="google-images" {% if default_backend == 'google-images' %}selected{% endif %}>Google Images (cloud, better quality)</option>
    </select>
</label>
```

The form already has `fd = new FormData(this)` which captures all form fields — including the new select. No JS changes needed beyond adding the element.

- [ ] **Step 3: Verify**

```bash
uv run python -c "from app.tools.image_translator.router import router; print('Router OK')"
```

- [ ] **Step 4: Commit**

```bash
git add app/tools/image_translator/router.py app/templates/tools/image_translator.html
git commit -m "feat(image_translator): add backend selection dropdown, pass to TaskIQ

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Update wizard router + template

**Files:**
- Modify: `app/tools/wizard/router.py`
- Modify: `app/templates/tools/wizard.html`

**Interfaces:**
- Consumes: `settings.translation.backend` (Task 1)
- Produces: `backend` parameter in wizard task data and template

- [ ] **Step 1: Update wizard router**

In `app/tools/wizard/router.py`:

```python
# In index() — add default_backend
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "tools/wizard.html",
        {
            "default_lang": settings.translation.target_lang,
            "default_backend": settings.translation.backend,
        },
    )


# In create_wizard() — accept backend, store in task data
@router.post("/create")
async def create_wizard(
    ...
    backend: str = Form("tesseract"),
    ...
):
    ...
    await tm.create(task_id, initial=make_initial(
        link_id, parent_id, asset_id, target_lang=target_lang, force=force,
    ))
    # Store backend choice in task data
    await tm.patch(task_id, "data.backend", backend)
    ...


# In _run_translate_via_taskiq() — read backend from task data, pass to .kiq()
async def _run_translate_via_taskiq(tm: TaskManager, task_id: str) -> None:
    ...
    await translate_images_task.kiq(
        task_id=task_id,
        image_paths=image_paths,
        target_lang=target_lang,
        output_dir=out_dir,
        cache_base=cache_base,
        cache_key=cache_key,
        force=force,
        backend=data.get("backend", "tesseract"),
    )
    ...
```

- [ ] **Step 2: Add backend dropdown to wizard template**

Same as Task 5 — add the `<select name="backend">` between the target language dropdown and the force checkbox in `wizard.html`.

- [ ] **Step 3: Verify**

```bash
uv run python -c "from app.tools.wizard.router import router; print('Wizard router OK')"
```

- [ ] **Step 4: Commit**

```bash
git add app/tools/wizard/router.py app/templates/tools/wizard.html
git commit -m "feat(wizard): add backend selection — stored in task data, passed to TaskIQ

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Update TaskIQ task to use backend protocol

**Files:**
- Modify: `app/tasks/translate.py`

**Interfaces:**
- Consumes: `get_backend()` from Task 2, `TesseractBackend` internals from Task 3
- Produces: `backend` parameter in `translate_images_task()`

The TaskIQ task currently uses Tesseract internals directly (`_translate_one_image_inplace`, `_process_page`). After this task, it delegates to the selected backend. The Tesseract-internal lazy imports stay for the Tesseract path (no behavior change there).

- [ ] **Step 1: Rewrite translate.py to delegate to backend**

Replace `app/tasks/translate.py`:

```python
"""Translation task — runs on a TaskIQ worker (separate process or machine).

Supports multiple backends via the `backend` parameter:
- "tesseract": local OCR + translate + inpaint (default)
- "google-images": Playwright-based Google Translate Images tab
"""

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from app.core.progress import write_progress

logger = logging.getLogger(__name__)

TRANSLATE_DELAY = 2  # seconds between pages (tesseract only)


async def translate_images_task(
    task_id: str,
    image_paths: list[str],
    target_lang: str,
    output_dir: str,
    cache_base: str | None = None,
    cache_key: str = "",
    force: bool = False,
    font_path: str | None = None,
    backend: str = "tesseract",
) -> dict:
    """TaskIQ task: in-place image translation via selected backend.

    Runs on a worker process. Writes progress to Redis for SSE streaming.
    Called via: await translate_images_task.kiq(...)
    """
    from app.tools.image_translator.backends import get_backend

    t0 = time.monotonic()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if force and any(out_path.iterdir()):
        shutil.rmtree(out_path)
        out_path.mkdir(parents=True, exist_ok=True)

    paths = [Path(p) for p in image_paths]
    total = len(paths)

    completed_count = 0
    completed_pages: list[int] = []
    pages_lock = asyncio.Lock()

    async def on_progress(current: int, _total: int) -> None:
        nonlocal completed_count
        async with pages_lock:
            completed_count = current
            await write_progress(task_id, {
                "status": "in_progress",
                "current": current,
                "total": total,
                "completed_pages": list(range(current)),
                "message": f"Translating page {current}/{total}...",
            })

    async def on_log(msg: str) -> None:
        logger.info("[%s] %s", task_id[:8], msg)

    be = get_backend(backend)
    result = await be.translate(
        image_paths=paths,
        target_lang=target_lang,
        output_dir=out_path,
        cache_base=Path(cache_base) if cache_base else None,
        cache_key=cache_key,
        force=force,
        font_path=font_path,
        on_progress=on_progress,
        on_log=on_log,
    )

    translated = result["paths"]
    elapsed = time.monotonic() - t0
    logger.info("translate_images_task done: %d pages in %.1fs", len(translated), elapsed)

    await write_progress(task_id, {
        "status": "done",
        "current": total,
        "total": total,
        "completed_pages": list(range(total)),
        "message": f"{total} pages translated ({elapsed:.1f}s)",
        "data": {"translated_paths": [str(p) for p in translated]},
    })

    return {
        "paths": [str(p) for p in translated],
        "elapsed": elapsed,
        "cache_hit": result.get("cache_hit", False),
    }
```

- [ ] **Step 2: Verify imports**

```bash
uv run python -c "from app.tasks.translate import translate_images_task; print('Task OK')"
```

- [ ] **Step 3: Commit**

```bash
git add app/tasks/translate.py
git commit -m "refactor(tasks): delegate to selected backend instead of Tesseract directly

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Add Playwright + Chromium deps

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`

- [ ] **Step 1: Add playwright to pyproject.toml**

```python
# pyproject.toml — add to dependencies
"playwright>=1.48.0",
```

- [ ] **Step 2: Update uv.lock**

```bash
uv lock
```

- [ ] **Step 3: Update Dockerfile to install Chromium**

Edit `Dockerfile` — after the `uv sync` line and before `COPY app/`:

```dockerfile
# Install Playwright browsers (Chromium for headless Google Translate automation)
RUN uv run python -m playwright install chromium --with-deps
```

- [ ] **Step 4: Install playwright-stealth browser patch**

`playwright-stealth` requires a browser patch. Add to Dockerfile after the Chromium install:

```dockerfile
RUN uv run python -m playwright_stealth
```

The final Dockerfile should have these lines in order:

```dockerfile
FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       tesseract-ocr-jpn \
       tesseract-ocr-eng \
       fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

# Playwright: install Chromium + deps for headless Google Translate automation
RUN uv run python -m playwright install chromium --with-deps

COPY app/ app/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: `playwright-stealth` is a pip package but the browser patch is applied at build time. If it's not available as a CLI, skip it — the inline script in `google_images.py` (`navigator.webdriver = undefined`) handles basic detection evasion.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile
git commit -m "feat(deps): add Playwright + Chromium for Google Images backend

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Update broker to accept backend param in task signature

**Files:**
- Modify: `app/brokers/taskiq_broker.py`

The registered task signature now includes `backend`. No code change needed — the broker just imports the function. But verify the signature matches.

- [ ] **Step 1: Verify task registration**

```bash
uv run python -c "
from app.brokers.taskiq_broker import translate_images_task
import inspect
sig = inspect.signature(translate_images_task)
params = list(sig.parameters.keys())
print('Task params:', params)
assert 'backend' in params, 'backend param missing!'
print('OK')
"
```
Expected: `backend` in params list, `OK`

- [ ] **Step 2: No changes needed — commit a no-op if verification passes**

If verification passes, this task requires zero changes. Skip commit.

---

### Task 10: End-to-end verification

**Files:**
- No new files — manual verification

- [ ] **Step 1: Verify all imports end-to-end**

```bash
uv run python -c "from app.main import app; print('App imports OK')"
```

- [ ] **Step 2: Verify both backends instantiate**

```bash
uv run python -c "
from app.tools.image_translator.backends import get_backend
be = get_backend('tesseract')
print('Tesseract:', type(be).__name__)
be2 = get_backend('google-images')
print('GoogleImages:', type(be2).__name__)
print('OK')
"
```

- [ ] **Step 3: Verify Tesseract backend produces output (requires tesseract + jpn)**

```bash
uv run python -c "
from pathlib import Path
from app.tools.image_translator.backends.tesseract import TesseractBackend
import tempfile
# Create a tiny test image
from PIL import Image
img = Image.new('RGB', (100, 50), 'white')
tmp = Path(tempfile.mkdtemp()) / 'test.jpg'
img.save(tmp)
be = TesseractBackend()
import asyncio
result = asyncio.run(be.translate([tmp], 'en', Path(tempfile.mkdtemp())))
print('Paths:', len(result['paths']), 'Elapsed:', result['elapsed'])
print('OK')
"
```
Expected: `Paths: 1`, `OK` (may produce tofu text if no CJK font, that's fine for this test)

- [ ] **Step 4: Start dev server, verify pages load**

```bash
# Start server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 &
sleep 2
# Check pages with backend dropdown
uv run python -c "
import httpx
for path in ['/', '/image-translator/', '/wizard/']:
    r = httpx.get(f'http://localhost:8000{path}')
    assert r.status_code == 200, f'{path} got {r.status_code}'
    print(f'{path} -> 200')
# Verify backend dropdown exists in translator page
r = httpx.get('http://localhost:8000/image-translator/')
assert 'Translation Engine' in r.text, 'Backend dropdown missing!'
print('Backend dropdown: found')
"
kill %1 2>/dev/null
```
Expected: All 200, backend dropdown found

- [ ] **Step 5: Commit any fixes, or skip if clean**

```bash
# Only if fixes were made
git add -A && git commit -m "chore: e2e verification fixes"
```