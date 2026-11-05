# Work Utilities App — Project Requirements & Architecture

## Overview

A personal, monolithic web application containing utility tools for daily work tasks (e.g. download images, merge images into a PDF, translate PDF from Japanese to English). Built for extensibility: adding a new tool should be minimal and mechanical.

---

## Goals & Constraints

- **Monolithic** — single deployable unit, no microservices
- **Functional first** — aesthetics are secondary, but a component library is used for consistency and developer speed
- **Extensibility** — adding a new tool must follow a clear, repeatable contract
- **Solo developer** — avoid over-engineering; defer complexity until there is a concrete need
- **DRY, KISS, best practices** — no premature abstractions

---

## Tech Stack

### Backend
- **Language:** Python
- **Framework:** FastAPI
  - `APIRouter` per tool for clean separation
  - `BackgroundTasks` for async file processing (short-lived jobs)
  - `StreamingResponse` for file downloads — stream and delete, never serve from static
  - Jinja2 for server-side HTML templating (ships with FastAPI)

### Frontend
- **Rendering:** Server-rendered HTML via Jinja2 templates
- **Interactivity:** HTMX — used minimally and purposefully:
  - Job status polling (`hx-get` + `hx-trigger="every 2s"`) for background tasks
  - Form submit without full page reload for tool results
  - NOT used as a general framework — plain HTML forms are the default
- **CSS:** Tailwind CSS + DaisyUI via CDN
  - No build step required (CDN is acceptable for an internal/personal tool)
  - DaisyUI provides a ShadCN-equivalent component system for server-rendered HTML
  - Add Tailwind build pipeline only if bundle size becomes a concern

### Configuration
- **`pydantic-settings`** for all app configuration
  - Single `config.py` with a `Settings` class
  - Typed, validated at startup — misconfigured env vars fail fast
  - All secrets and environment-specific values via `.env`
  - `.env.example` committed to repo as documentation

### Package Manager & Tooling
- **`uv`** — package manager, virtual environment, script runner (replaces pip + venv + Poetry)
- **`uvx`** — for running tools without installing (e.g. `uvx ruff check .`)
- **`ruff`** — linting + formatting (replaces flake8 + black + isort)
- **`pyright`** — type checking
  - Strict on `service.py` files (pure business logic)
  - Standard on routers
- **`pytest`** — testing

### Database
- **Now:** None. No persistence needed for a stateless file-processing utility.
- **Future:** NeonDB (serverless Postgres) via SQLAlchemy + Alembic when job history or user data is needed.
  - `settings.database_url` is already wired in `Settings` (set to `None` by default).

### Task Queue
- **Now:** FastAPI `BackgroundTasks` — runs in-process after response is sent, sufficient for short jobs.
- **Future:** **Taskiq** (not ARQ — ARQ is in maintenance mode) when:
  - Tasks consistently exceed ~30 seconds
  - Retry logic is needed
  - Job status visibility across requests is required
  - `settings.broker_url` is already wired in `Settings` (set to `None` by default).

---

## Project Structure

```
app/
├── main.py                        # App factory, router + middleware registration
├── config.py                      # pydantic-settings Settings class — single source of truth
├── dependencies.py                # Shared FastAPI dependencies (e.g. get_settings)
│
├── tools/
│   ├── image_downloader/
│   │   ├── router.py              # FastAPI APIRouter — HTTP layer only
│   │   ├── service.py             # Business logic — pure Python, no FastAPI imports
│   │   └── schemas.py             # Pydantic request/response models
│   ├── image_to_pdf/
│   │   ├── router.py
│   │   ├── service.py
│   │   └── schemas.py
│   └── pdf_translator/
│       ├── router.py
│       ├── service.py
│       └── schemas.py
│
├── templates/
│   ├── base.html                  # Layout, nav, Tailwind + DaisyUI CDN, HTMX CDN
│   ├── index.html                 # Dashboard — list of all tools
│   └── tools/
│       ├── image_downloader.html
│       ├── image_to_pdf.html
│       └── pdf_translator.html
│
├── core/
│   ├── files.py                   # Shared: save uploads, cleanup temp files
│   └── responses.py               # Shared: StreamingResponse file download helper
│
├── static/
│   └── app.css                    # Minimal overrides only — prefer DaisyUI classes
│
├── tests/
│   ├── test_image_to_pdf.py       # Test service.py directly — no HTTP needed
│   └── test_pdf_translator.py
│
├── pyproject.toml                 # uv + ruff + pyright config
├── .env                           # Secrets — never committed
└── .env.example                   # Committed — documents all required env vars
```

---

## Extensibility Contract

Adding a new tool is always exactly these steps:

```
1. mkdir app/tools/new_tool/
2. Create router.py   — APIRouter with route(s)
3. Create service.py  — pure Python business logic, no FastAPI imports
4. Create schemas.py  — Pydantic models for request/response
5. Create templates/tools/new_tool.html
6. Register in main.py:
     from tools.new_tool.router import router as new_tool_router
     app.include_router(new_tool_router, prefix="/new-tool", tags=["new-tool"])
```

The `service.py` constraint (no FastAPI imports) is intentional:
- Testable without an HTTP server
- Reusable if a CLI or scheduled job is added later
- Clean separation of concerns

---

## Configuration (`config.py`)

```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # App
    app_name: str = "Work Utilities"
    debug: bool = False

    # Paths
    temp_dir: Path = Path("/tmp/worktools")
    max_upload_mb: int = 50

    # External APIs
    translation_api_key: str
    translation_api_url: str = "https://api.deepl.com/v2"

    # Future — set to None until needed
    database_url: str | None = None    # NeonDB Postgres connection string
    broker_url: str | None = None      # Taskiq broker URL

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
```

---

## File Handling Strategy

- **Uploads:** saved to `settings.temp_dir / "uploads"`
- **Outputs:** saved to `settings.temp_dir / "outputs"`
- **Never** serve files from static directory
- **Always** use `StreamingResponse` + a `BackgroundTask` to delete the file after streaming
- No permanent file storage — this is a stateless processing app

---

## Key Python Libraries

```
fastapi
uvicorn[standard]
jinja2
python-multipart        # multipart form / file upload support
httpx                   # async HTTP client (image downloader)
Pillow                  # image processing
pymupdf                 # PDF manipulation — best in class
python-dotenv
pydantic-settings
```

Note: `sharp` (Node.js) was evaluated and ruled out based on prior negative experience. `Pillow` + `pymupdf` are the standard for Python image/PDF work.

---

## Tooling Configuration (`pyproject.toml`)

```toml
[project]
name = "work-utilities"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]    # errors, pyflakes, import sorting, pyupgrade

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "standard"
```

---

## Editor Setup (VS Code)

Extensions:
- `ms-python.python`
- `ms-python.vscode-pylance`
- `charliermarsh.ruff`
- `batisteo.vscode-django` — Jinja2 template highlighting
- `htmx-tags.html-htmx-tags` — HTMX attribute autocomplete

`settings.json`:
```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  }
}
```

---

## HTMX Usage Rules

HTMX is a scalpel, not a foundation. Use it only for:

| Pattern | HTMX attribute |
|---|---|
| Poll job status after background task starts | `hx-get="/job/{id}/status" hx-trigger="every 2s"` |
| Submit form, replace result section in-place | `hx-post="/tool" hx-target="#result"` |

Do NOT use HTMX for navigation, file downloads, or anything a plain HTML form handles naturally.

---

## DaisyUI Component Usage

DaisyUI is used for all UI components. It is Tailwind-based and requires no JavaScript framework.

```html
<!-- Buttons -->
<button class="btn btn-primary">Process</button>

<!-- Cards (tool container) -->
<div class="card bg-base-100 shadow">
  <div class="card-body">...</div>
</div>

<!-- File input -->
<input type="file" class="file-input file-input-bordered w-full" />

<!-- Progress (shown during background task) -->
<progress class="progress progress-primary w-full"></progress>

<!-- Alerts -->
<div class="alert alert-success">Done!</div>
<div class="alert alert-error">Something went wrong.</div>
```

---

## Scalability Roadmap (Defer Until Needed)

| Stage | Trigger | Action |
|---|---|---|
| More tools | Any new utility needed | Follow extensibility contract — one folder, two lines in main.py |
| Tasks time out | Jobs consistently exceed ~30s | Add Taskiq + Redis broker; task function signatures don't change |
| Persistence needed | Job history, audit log, user prefs | Add NeonDB via SQLAlchemy + Alembic; `database_url` already in Settings |
| Auth needed | App exposed beyond localhost | FastAPI OAuth2/JWT — add to `dependencies.py` |
| Rich frontend needed | Drag-and-drop, live preview, complex UI | FastAPI becomes a pure API; point a Next.js or SvelteKit frontend at it; `service.py` layer unchanged |
| Bundle size matters | Load time becomes a concern | Add Tailwind build pipeline (PostCSS + purge); no Python changes |
| Deploy to server | Ready for production | Docker + uvicorn + nginx, or Railway/Fly.io |

---

## Build & Run

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project and install dependencies
uv init work-utilities
cd work-utilities
uv add fastapi uvicorn[standard] jinja2 python-multipart httpx pillow pymupdf pydantic-settings
uv add --dev ruff pyright pytest

# Run dev server
uv run uvicorn app.main:app --reload

# Lint
uvx ruff check .

# Format
uvx ruff format .

# Type check
uv run pyright

# Test
uv run pytest
```

---

## Implementation Order

1. **Shell** — `main.py` + `base.html` with DaisyUI CDN, empty nav with tool links
2. **`image_to_pdf` tool** — establishes the full pattern end-to-end (router → service → template → download)
3. **`image_downloader` tool** — validates that the extensibility contract works for a second tool
4. **`pdf_translator` tool** — add last; has external API dependency (translation key, cost)

Each subsequent tool is a copy of the folder structure with new logic in `service.py`. That is the entire system.
