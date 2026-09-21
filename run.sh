#!/usr/bin/env bash
# Noesis PDF Cloner — Service: avvia il server (uvicorn, processo singolo).
#
# La coda e i semafori del motore sono in memoria: il servizio DEVE girare con
# un solo processo uvicorn (--workers 1). Il parallelismo è interno (thread).
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

if [ ! -d .venv2 ]; then
  echo "Suggerimento: esegui ./setup_engine.sh per installare il motore pdf2zh_next."
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18080}"
exec .venv/bin/python -m uvicorn app.main:app --workers 1 --host "$HOST" --port "$PORT"
