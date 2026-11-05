# Architecture

How this app is put together, for anyone reading or extending the code.

## Shape

A single FastAPI application with server-rendered FastHTML pages, plus a
TaskIQ worker for the slow OCR jobs. Redis is the task broker and the
progress store. One deployable unit (Docker Compose), no microservices.

```
browser ──▶ web (FastAPI/FastHTML)
                │ taskiq .kiq()
                ▼
             redis ◀── worker (TaskIQ, PaddleOCR)
```

## Layout

```
app/
├── main.py                  # FastAPI app: auth, routers, lifespan
├── fh_app.py                # shared FastHTML instance (rt decorator)
├── ui.py                    # page shell: nav, head, footer
├── views.py                 # home page
├── config.py                # pydantic-settings, per-prefix sections
├── core/                    # shared services, tool-agnostic
│   ├── ocr.py               # PaddleOCR wrapper (text detection + recognition)
│   ├── japanese.py          # furigana tokenization (pykakasi-based)
│   ├── translate.py         # provider registry: google/deepl/lingva/mymemory
│   ├── translation_cache.py # phrase-level cache in Redis
│   ├── render.py            # painting translated text back onto images
│   ├── progress.py          # task progress, published via Redis pub/sub
│   ├── auth.py              # shared APP_PASSWORD write gate
│   └── jr_store.py          # jp_reader page store (filesystem + Redis)
├── brokers/taskiq_broker.py # Redis broker, worker tasks registered here
├── tasks/jp_reader.py       # the OCR task the worker runs
└── tools/
    ├── jp_reader/           # upload → OCR → annotated page
    │   ├── router.py        #   JSON API (upload, status, regions, delete)
    │   ├── views.py         #   server-rendered pages (list, detail)
    │   ├── service.py       #   orchestration, store access
    │   ├── transform.py     #   image transforms (rotate/straighten/crop)
    │   └── schemas.py
    └── jp_translator/       # two-panel ja↔en translation with furigana
        ├── router.py
        ├── views.py
        ├── service.py
        └── schemas.py
```

## Adding a tool

A tool is a directory under `app/tools/` with `router.py` (JSON API under
`/api/...`), `views.py` (FastHTML pages under its own prefix), and
`schemas.py`. Register the router in `app/main.py`, add a card to the home
page in `app/views.py`, and an entry in the page registry in `app/ui.py`.
Heavy work goes through TaskIQ (`app/tasks/`), with progress published via
`app/core/progress.py`.

## Conventions

- **Config**: pydantic-settings sections with env prefixes (`APP_`, `JR_`,
  `JPT_`, `TRANSLATION_`, `REDIS_URL`). `.env.example` documents all of them.
- **Auth**: one shared `APP_PASSWORD` gates all writes; reads are open.
- **Tests** live in `app/tests/` and run against the service layer and API;
  `uv run pytest -q`. Lint with `uv run ruff check app scripts`, types with
  `uv run pyright app/`.
- **Docs**: `docs/deployment.md` for the VPS setup; `docs/superpowers/`
  holds the planning notes that drove each feature.
