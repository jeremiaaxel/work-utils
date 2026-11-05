# ---------- base: shared setup for every image ----------
FROM python:3.12-slim AS base

WORKDIR /app

# Copy project definition first for layer caching
COPY pyproject.toml uv.lock ./

# The worker reloads on source changes and filters them with .gitignore —
# without this file it would reload on every __pycache__ write and never
# finish a task.
COPY .gitignore ./

# ---------- uv: the package manager, kept out of the shipped images ----------
FROM base AS uv

# Pinned: ":latest" makes the build unreproducible.
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /bin/

# ---------- deps-web: the virtualenv for the web process ----------
# No OCR stack here — the web never imports paddle. Keeps this image small.
FROM uv AS deps-web

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-default-groups --no-install-project --frozen

# ---------- deps-worker: the virtualenv for the worker ----------
FROM uv AS deps-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project --frozen

# ---------- ocr-runtime: system packages the worker needs ----------
FROM base AS ocr-runtime

# paddleocr[all] pulls opencv-contrib-python (a non-headless build), which
# needs libGL. libgomp is the OpenMP runtime paddle's libpaddle.so loads —
# it used to arrive as a side-effect of tesseract, so it is named here now.
# fonts-noto-cjk is the CJK font the translated-page renderer falls back to.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       fonts-noto-cjk \
       libgl1 \
       libglib2.0-0 \
       libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ---------- models: the OCR weights, fetched once ----------
# Its own stage, so that a change to the app never invalidates it. Without
# this the 139 MB of weights were downloaded again on every deploy.
#
# Only the files the warm-up actually reads are copied — copying a whole
# directory would tie the cached weights to every change inside it.
FROM ocr-runtime AS models

COPY --from=deps-worker /app/.venv /app/.venv
COPY app/__init__.py app/__init__.py
COPY app/core/__init__.py app/core/__init__.py
COPY app/core/ocr.py app/core/ocr.py
COPY app/warmup.py app/warmup.py

RUN /app/.venv/bin/python -m app.warmup

# ---------- web (production) ----------
FROM base AS web

COPY --from=deps-web /app/.venv /app/.venv
COPY app/ app/

EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------- worker (production) ----------
FROM ocr-runtime AS worker

COPY --from=deps-worker /app/.venv /app/.venv
COPY --from=models /root/.paddlex /root/.paddlex
COPY app/ app/

# ---------- dev images: no virtualenv baked in ----------
# The dev containers install into a volume mounted at /app/.venv, so a venv in
# the image would be shadowed and thrown away — while costing minutes on
# every build. The dev command installs it at start-up instead.
FROM base AS web-dev

COPY --from=uv /bin/uv /bin/uvx /bin/
COPY app/ app/

EXPOSE 8000

FROM ocr-runtime AS worker-dev

COPY --from=uv /bin/uv /bin/uvx /bin/
COPY app/ app/
