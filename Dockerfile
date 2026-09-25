# syntax=docker/dockerfile:1.7
#
# Noesis PDF Cloner Service — immagine multi-arch (linux/amd64, linux/arm64).
#
# Contiene entrambi i venv (servizio + motore pdf2zh_next) e gli asset BabelDOC
# pre-scaricati (`babeldoc --warmup`), così il container è pronto all'uso:
#
#   docker run -d -p 18080:18080 -v noesis-data:/data \
#     ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
#
# Vedi docs/DOCKER.md.

# Base pinnata per digest (hardening supply-chain). Aggiorna il digest con
#   docker buildx imagetools inspect python:3.12-slim-bookworm
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

# ── variabili comuni ──────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/tmp/uv-cache

# ── librerie di sistema minime ────────────────────────────────────────────
# libgomp1: onnxruntime/scipy · libglib2.0-0: opencv (headless) · tini: PID 1
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl libgomp1 libglib2.0-0 tini \
 && rm -rf /var/lib/apt/lists/*

# uv: serve solo in build (per creare i venv e installare le dipendenze).
# Pinnato per digest (era `latest`): aggiornalo con
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /usr/local/bin/uv

# ── utente non-root e cartelle ────────────────────────────────────────────
ARG APP_UID=1000
RUN useradd --create-home --uid "${APP_UID}" --shell /usr/sbin/nologin noesis \
 && mkdir -p /app /data \
 && chown -R noesis:noesis /app /data /home/noesis

# La cache BabelDOC vive nella HOME dell'utente (asset pre-scaricati in build).
ENV HOME=/home/noesis

WORKDIR /app

# ── venv del servizio (.venv) ─────────────────────────────────────────────
COPY requirements.txt ./
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv venv --python /usr/local/bin/python3.12 .venv \
 && uv pip install --python .venv/bin/python -r requirements.txt

# ── venv del motore (.venv2), da lockfile riproducibile ───────────────────
COPY requirements-engine.txt requirements-engine.lock ./
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv venv --python /usr/local/bin/python3.12 .venv2 \
 && uv pip install --python .venv2/bin/python -r requirements-engine.lock

# ── codice applicativo ────────────────────────────────────────────────────
COPY . .
RUN chmod +x /app/docker/entrypoint.sh

# ── asset BabelDOC pre-scaricati (modelli + font + cmap + tiktoken) ───────
RUN .venv2/bin/babeldoc --warmup \
 && chown -R noesis:noesis /home/noesis

# ── runtime ───────────────────────────────────────────────────────────────
ENV HOST=0.0.0.0 \
    PORT=18080 \
    DATA_DIR=/data \
    PDF2ZH_BIN=/app/.venv2/bin/pdf2zh_next \
    PATH="/app/.venv/bin:${PATH}"

LABEL org.opencontainers.image.source="https://github.com/vigliafg/noesis-pdf-cloner-service" \
      org.opencontainers.image.title="noesis-pdf-cloner-service" \
      org.opencontainers.image.description="Traduzione PDF con layout preservato: server + coda + CLI" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

EXPOSE 18080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" || exit 1

USER noesis
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
