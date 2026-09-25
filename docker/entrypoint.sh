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

# Configurazione: le variabili d'ambiente del container hanno la precedenza, ma
# l'app legge anche "$DATA_DIR/noesis.env" (creato dalla pagina /settings o da
# `docker exec noesis ./noesis config --set ...`). Una variabile vuota (es.
# OPENROUTER_API_KEY="") vale come "non impostata".

# Con ROLE=all coda e semafori del motore sono locali → un solo processo uvicorn.
# Con ROLE=worker si consuma la coda senza esporre HTTP (come run-worker.sh).
if [ "$ROLE" = "worker" ]; then
    exec python -m app.worker_main
fi

workers=1
if [ "$ROLE" = "api" ]; then
    workers="${UVICORN_WORKERS:-1}"
fi

exec python -m uvicorn app.main:app \
    --host "$HOST" --port "$PORT" --workers "$workers"
