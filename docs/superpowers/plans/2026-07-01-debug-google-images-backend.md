# Debug: Google Images Translation Backend Timing Out

> **STATUS: ACTIVE** — Every page times out after 60s. Google may be blocking, or the page structure has changed.

**Problem:** `_translate_one_page()` consistently times out at `result_img.wait_for(state="visible", timeout=60_000)`. This means either:
1. The upload never triggers (wrong selector, consent wall, CAPTCHA)
2. The translation starts but the result selector (`div[role="main"] img`) never matches
3. Google is serving a different page entirely (rate limit, bot detection)

---

### Debug Step 1: Screenshot the page state on timeout

**Goal:** See what Google actually rendered — consent dialog, CAPTCHA, error page, or the translate UI with no result.

**File:** `app/tools/image_translator/backends/google_images.py`

In `_translate_one_page()`, before raising the timeout error, save a screenshot + page HTML:

```python
except PlaywrightTimeout:
    # DEBUG: capture what Google actually shows
    debug_dir = out_path.parent / "_debug"
    debug_dir.mkdir(exist_ok=True)
    page_name = out_path.stem  # e.g. "page-00"
    await page.screenshot(path=str(debug_dir / f"{page_name}_screenshot.png"))
    html = await page.content()
    (debug_dir / f"{page_name}_page.html").write_text(html, encoding="utf-8")
    logger.error("Page %s timed out — saved debug artifacts to %s", page_name, debug_dir)
    raise RuntimeError(
        f"Translation timed out after {timeout}s. Google may be slow or blocking."
    )
```

**How to check:** After the task fails, look in the task's output dir for `_debug/` — open the screenshot and HTML.

---

### Debug Step 2: Add detailed logging at each selector stage

**Goal:** Pinpoint exactly which step hangs — page load, file input wait, upload, result wait.

**File:** `app/tools/image_translator/backends/google_images.py`

Replace the silent steps in `_translate_one_page()` with logged checkpoints:

```python
async def _translate_one_page(page, img_path, target_lang, out_path, *, timeout=60):
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    url = _build_url(target_lang)
    logger.info("[google] navigating to %s", url)
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    logger.info("[google] page loaded, title=%s, url=%s", await page.title(), page.url)

    # Check for consent/cookie wall
    consent_btns = [
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button:has-text("同意")',
        '[aria-label="Accept all"]',
    ]
    for sel in consent_btns:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2_000):
                logger.info("[google] clicking consent button: %s", sel)
                await btn.click()
                await page.wait_for_timeout(1_000)
                break
        except Exception:
            pass

    logger.info("[google] waiting for file input...")
    await page.wait_for_selector('input[type="file"]', state="attached", timeout=15_000)
    logger.info("[google] file input found, uploading %s (%.1fKB)", img_path.name, img_path.stat().st_size / 1024)

    file_input = page.locator('input[type="file"]').first
    await file_input.set_input_files(str(img_path))
    logger.info("[google] file uploaded, waiting for result...")

    # ... rest of result extraction ...
```

**How to check:** Worker logs will show exactly where it gets stuck.

---

### Debug Step 3: Verify selectors against live Google Translate

**Goal:** Confirm the selectors still match Google's current DOM.

Run this one-shot script inside the Docker container (or locally with playwright installed):

```bash
docker compose run --rm -e GOOGLE_TRANSLATE_TIMEOUT=120 dev \
  uv run python -c "
import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        await page.goto('https://translate.google.com/?sl=auto&tl=en&op=images', wait_until='domcontentloaded')
        print('Title:', await page.title())
        print('URL:', page.url)

        # Check for file input
        file_inputs = await page.query_selector_all('input[type=\"file\"]')
        print('File inputs found:', len(file_inputs))

        # Check for consent dialogs
        for text in ['Accept', 'I agree', '同意', 'Reject']:
            el = page.locator(f'button:has-text(\"{text}\")').first
            visible = await el.is_visible() if await el.count() > 0 else False
            if visible:
                print(f'Consent button visible: {text}')

        # Dump key DOM structure
        html = await page.content()
        # Save for manual inspection
        with open('/tmp/google-translate-page.html', 'w') as f:
            f.write(html)
        print('Saved HTML to /tmp/google-translate-page.html')

        # Try uploading a tiny test image
        from PIL import Image
        test_img = '/tmp/test-page.jpg'
        Image.new('RGB', (100, 50), 'white').save(test_img)

        file_input = page.locator('input[type=\"file\"]').first
        await file_input.set_input_files(test_img)
        print('Uploaded test image, waiting 10s...')
        await page.wait_for_timeout(10_000)

        # What's on screen now?
        await page.screenshot(path='/tmp/google-after-upload.png')
        print('Saved screenshot to /tmp/google-after-upload.png')

        # Check for result images
        imgs = await page.query_selector_all('div[role=\"main\"] img')
        print(f'Result images (div[role=main] img): {len(imgs)}')
        all_imgs = await page.query_selector_all('img')
        print(f'Total img tags: {len(all_imgs)}')

        await browser.close()

asyncio.run(inspect())
"
```

**How to check:** Look at the screenshot and HTML to see what Google actually shows.

---

### Debug Step 4: Check if Google serves different content to datacenter IPs

**Goal:** Docker containers often run on datacenter IPs that Google rate-limits or serves CAPTCHAs to.

Symptoms to look for in debug artifacts from Step 1:
- "Before you continue" consent wall (EU GDPR)
- CAPTCHA / "unusual traffic" page
- Empty translate page with no file input
- `sorry/index` Google block page

**Mitigation ideas to test after confirming:**
- Route through a residential proxy (`--proxy-server` in Chromium args)
- Use `PLAYWRIGHT_PROXY_URL` env var to configure
- Lower parallelism (already at 1, so this is fine)
- Add longer initial delay before first upload

---

### Debug Step 5: Network-level — is the upload actually reaching Google?

**Goal:** Rule out Docker networking issues.

Inside the container:
```bash
docker compose exec dev curl -v -o /dev/null 'https://translate.google.com/?sl=auto&tl=en&op=images'
```

Check:
- Does DNS resolve? (should go to a Google IP)
- Does TLS handshake complete? (should get 200)
- Is the response HTML or a redirect?

---

### Priority Order

1. **Step 1** (screenshot on timeout) — lowest effort, highest diagnostic value. Add it, run one task, look at the screenshot.
2. **Step 2** (logging) — add alongside Step 1, gives timing info.
3. **Step 3** (one-shot inspection) — if Step 1 screenshot is unclear, run this for a clean interactive test.
4. **Step 4/5** — only if Steps 1-3 show Google is blocking the IP.

### Hypotheses (most → least likely)

| # | Hypothesis | Evidence to look for |
|---|-----------|---------------------|
| 1 | Google changed DOM — selectors don't match | Screenshot shows translate UI but no result, `div[role="main"] img` count is 0 |
| 2 | Consent/cookie wall blocks the upload | Screenshot shows "Before you continue" dialog |
| 3 | CAPTCHA / bot detection | Screenshot shows CAPTCHA or "unusual traffic" |
| 4 | File upload selector wrong | Logs show "file input found" but upload doesn't trigger any network activity |
| 5 | Datacenter IP blocked | Steps 1-3 all show blocking/empty pages |
