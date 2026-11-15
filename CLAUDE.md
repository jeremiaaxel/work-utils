# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Personal Japanese-study web app with two tools: **JP Reader** (photograph a Japanese page → OCR → furigana + translation painted back over the image at a shareable URL) and **JP Translator** (two-panel ja↔en translation). AI-generated with a human in the loop; personal tool, not a product.

Stack: Python 3.12, FastAPI, server-rendered FastHTML (HTMX, Tailwind/DaisyUI via CDN), TaskIQ + Redis, PaddleOCR in a separate worker container, Docker Compose behind Caddy.

## Commands

```bash
uv sync                          # install deps incl. the heavy OCR group
uv run pytest -q                 # all tests
uv run pytest app/tests/test_translate.py -q        # one file
uv run pytest app/tests/test_translate.py::test_name # one test
uv run ruff check app scripts    # lint
uv run ruff check --fix app scripts                 # lint + autofix
uv run pyright app/              # types
```

Run the app locally: `docker compose --profile dev up --build` (starts web + OCR worker + Redis). A plain `uv run` web process cannot do OCR — the PaddleOCR stack runs only in the worker.

On every push to `main`: tests → lint → pyright → build web/worker images → push to GHCR → deploy over SSH. Local Docker is not needed for any of the checks; commit clean and push.

## Architecture

One FastAPI app, no microservices. The web process never runs OCR — slow jobs go through the task queue:

```
browser → web (FastAPI/FastHTML) --taskiq .kiq()--> redis <-- worker (TaskIQ, PaddleOCR)
```

- `app/main.py` — app factory; imports each tool's `views` for route registration side-effects and mounts each `router`.
- `app/fh_app.py` — shared FastHTML instance (`rt` decorator). Components are plain Python functions returning FT objects.
- `app/ui.py` — page shell (nav, head, footer), `page()` helper, `build_stamp()` cache-busting.
- `app/config.py` — pydantic-settings; env prefixes `APP_`, `JR_`, `JPT_`, `TRANSLATION_`, `REDIS_URL`. `.env.example` documents all of them.
- `app/core/` — tool-agnostic services: `ocr.py` (engine registry: paddle/tesseract), `japanese.py` (pykakasi furigana tokenization), `translate.py` (provider registry: google/deepl/lingva/mymemory), `runtime_settings.py` (Settings-page overrides in Redis, 2s in-process cache, reads never raise), `translation_cache.py` (phrase cache in Redis), `render.py` (painting text back onto images), `progress.py` (task progress via Redis pub/sub), `auth.py` (shared `APP_PASSWORD` write gate — reads open, all writes need the password), `jr_store.py` (jp_reader page store: filesystem + Redis).
- `app/tasks/jp_reader.py` — the OCR task the worker runs; `app/brokers/taskiq_broker.py` registers tasks.
- `app/tools/<tool>/` — each tool has `router.py` (JSON API under `/api/...`), `views.py` (FastHTML pages under its own prefix), `service.py`, `schemas.py`.

### Adding a tool

Directory under `app/tools/` with the four files above; register the router in `app/main.py`, add a home-page card in `app/views.py`, add an entry to the page registry in `app/ui.py`. Heavy work goes through TaskIQ with progress via `app/core/progress.py`.

### Testing pattern

Tests live in `app/tests/` and hit the service layer and API, not the browser. Redis-backed modules (`jr_store`, `progress`, `translation_cache`, `runtime_settings`) are monkeypatched onto `fakeredis` by the `fake_redis` fixture in `conftest.py` — use it rather than patching stores yourself; an autouse fixture keeps runtime-settings cache from leaking between tests.

### Runtime settings

`.env` supplies bootstrap defaults; overrides saved on the Settings page live in Redis and win until cleared. Both web and worker read the same keys, so changes apply to new jobs without a restart. New fields must be added to `_FIELDS` in `app/core/runtime_settings.py`.

### Deploy-sensitive details

- Keep the OCR dependencies in the `ocr` dependency group (not base deps) — it makes the web image ~1.6 GB smaller. Local `uv sync` gets it via default groups.
- CI pins Python to 3.12/3.13 (paddlepaddle has no 3.14 wheels).

## Docs

- `docs/deployment.md` — VPS setup (Caddy TLS, firewall, swap for PaddleOCR, deploy-key CI flow).
- `docs/superpowers/` — planning notes that drove each feature.
- `PROJECT_REQUIREMENTS.md` — the same architecture summary (this file mirrors it; keep both roughly in sync).
