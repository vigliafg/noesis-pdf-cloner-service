#!/usr/bin/env bash
# Noesis PDF Cloner — Service: avvia SOLO l'API (nessun worker).
#
# Da usare insieme a uno o più `run-worker.sh`: i job vengono accodati qui e
# reclamati dai processi worker tramite la coda condivisa su SQLite.
set -e
cd "$(dirname "$0")"

UV="${UV:-uv}"
if ! command -v "$UV" >/dev/null 2>&1; then
  echo "ERRORE: 'uv' non trovato. Installa uv (https://docs.astral.sh/uv/)" >&2
  exit 1
fi
if [ ! -d .venv ]; then
  "$UV" venv --python python3.12 .venv
fi
"$UV" pip install --python .venv/bin/python -q -r requirements.txt

export ROLE="${ROLE:-api}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18080}"
# L'API non esegue job: può girare con più processi uvicorn se serve.
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
exec .venv/bin/python -m uvicorn app.main:app \
  --workers "$UVICORN_WORKERS" --host "$HOST" --port "$PORT"
