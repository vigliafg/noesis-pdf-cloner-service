#!/usr/bin/env bash
# Installa/aggiorna il motore di clonazione pdf2zh_next v2 in .venv2 (Python 3.12).
set -e
cd "$(dirname "$0")"

UV="${UV:-uv}"
if ! command -v "$UV" >/dev/null 2>&1; then
  echo "ERRORE: 'uv' non trovato. Installa uv (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

if [ ! -d .venv2 ]; then
  "$UV" venv --python python3.12 .venv2
fi
"$UV" pip install --python .venv2/bin/python -q -r requirements-engine.txt

echo "Motore installato in .venv2"
echo "Pre-warm dei modelli (best effort, la prima pagina può richiedere più tempo)…"
.venv2/bin/pdf2zh_next --version 2>/dev/null || true
echo "Fatto. Verifica con: .venv/bin/python -m app.cli --check"
