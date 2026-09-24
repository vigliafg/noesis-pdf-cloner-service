#!/usr/bin/env bash
# Entrypoint del container: prepara la cartella dati e avvia uvicorn.
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18080}"
DATA_DIR="${DATA_DIR:-/data}"
ROLE="${ROLE:-all}"
export HOST PORT DATA_DIR ROLE

# La cartella dati (spesso un volume) deve essere scrivibile dall'utente noesis.
mkdir -p "$DATA_DIR" 2>/dev/null || true
if ! touch "$DATA_DIR/.write_test" 2>/dev/null; then
    echo "ERRORE: '$DATA_DIR' non è scrivibile (uid $(id -u))." >&2
    echo "Se usi un bind mount: sudo chown -R 1000:1000 <cartella-host>" >&2
    exit 1
fi
rm -f "$DATA_DIR/.write_test"

# Con ROLE=all coda e semafori del motore sono locali → un solo processo uvicorn.
workers=1
if [ "$ROLE" = "api" ]; then
    workers="${UVICORN_WORKERS:-1}"
fi

exec python -m uvicorn app.main:app \
    --host "$HOST" --port "$PORT" --workers "$workers"
