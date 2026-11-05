# work-utils

Personal web app for studying Japanese. Two tools:

- **JP Reader** — photograph a Japanese page; OCR extracts the text with
  furigana and translation, painted back over the image. Tap any word for
  its reading. Pages live at shareable URLs, so phone and laptop can look
  at the same page.
- **JP Translator** — two-panel Japanese↔English translation with furigana,
  copy-menu, and per-side pronunciation via the browser speech API.

> [!NOTE]
> This repository is AI-generated with a human in the loop: the code was
> written by Claude and reviewed, tested and deployed by a human. It is a
> personal tool, not a product — expect rough edges.

## Stack

| | |
|---|---|
| Backend | Python 3.12, FastAPI, TaskIQ + Redis |
| Frontend | Server-rendered FastHTML, HTMX, Tailwind/DaisyUI via CDN |
| OCR | PaddleOCR in a separate worker container |
| Translation | Pluggable providers: Google (web endpoint), DeepL, Lingva, MyMemory |
| Deploy | Docker Compose behind Caddy, images built in GitHub Actions |

## Run it

```bash
cp .env.example .env      # then edit: APP_PASSWORD, translation keys
docker compose --profile dev up --build
```

The app is on `http://localhost:8000`. A worker with the OCR stack runs in
a second container automatically.

For tests and linting without Docker:

```bash
uv sync
uv run pytest -q
uv run ruff check app scripts
uv run pyright app/
```

## Deploying

`docs/deployment.md` covers a single-VPS setup: Caddy for TLS, firewall,
swap sizing for PaddleOCR, and the deploy-key-restricted CI flow. On every
push to `main`, CI runs tests, lint, and type check, builds the web and
worker images to GHCR, and deploys over SSH.

## License

[MIT](LICENSE)
