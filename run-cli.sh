#!/usr/bin/env bash
# Noesis PDF Cloner — CLI headless (senza server).
#
#   ./run-cli.sh report.pdf -p 3,5,10-12 --dst it --engine bing --range-mode single
#   ./run-cli.sh *.pdf -p all --dst it --workers 2
#   ./run-cli.sh report.pdf --list-pages
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

exec .venv/bin/python -m app.cli "$@"
