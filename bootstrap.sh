#!/usr/bin/env bash
# Bootstrap: clona il repo (pubblico) e avvia l'installazione.
#
#   curl -LsSf https://raw.githubusercontent.com/vigliafg/noesis-pdf-cloner-service/main/bootstrap.sh | bash
#
# Variabili: NOESIS_DIR (destinazione), NOESIS_REPO_URL (default: GitHub).
set -euo pipefail
REPO_URL="${NOESIS_REPO_URL:-https://github.com/vigliafg/noesis-pdf-cloner-service.git}"
DEST="${NOESIS_DIR:-$HOME/noesis-pdf-cloner-service}"

if ! command -v git >/dev/null 2>&1; then
  echo "ERRORE: git non trovato. Installalo e riprova." >&2
  exit 1
fi

if [ -d "$DEST/.git" ]; then
  echo "· aggiorno $DEST"
  git -C "$DEST" pull --ff-only
else
  echo "· clono in $DEST"
  git clone "$REPO_URL" "$DEST"
fi

exec "$DEST/install.sh" "$@"
