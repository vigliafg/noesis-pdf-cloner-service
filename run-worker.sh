#!/usr/bin/env bash
# Noesis PDF Cloner — Service: avvia un processo WORKER (coda condivisa su DB).
#
# Per scalare su N processi worker:
#   WORKER_COUNT=4 ./run-worker.sh      # in 4 terminali/servizi
# Ogni worker divide automaticamente le risorse (CPU/RAM) per WORKER_COUNT.
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

export ROLE="${ROLE:-worker}"
export WORKER_COUNT="${WORKER_COUNT:-1}"
exec .venv/bin/python -m app.worker_main
