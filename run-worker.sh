#!/usr/bin/env bash
# Noesis PDF Cloner — Service: avvia un processo WORKER (coda condivisa su DB).
#
# Per scalare su N processi worker:
#   WORKER_COUNT=4 ./run-worker.sh      # in 4 terminali/servizi
# Ogni worker divide automaticamente le risorse (CPU/RAM) per WORKER_COUNT.
set -e
cd "$(dirname "$0")"

export ROLE="${ROLE:-worker}"
export WORKER_COUNT="${WORKER_COUNT:-1}"
exec ./noesis worker "$@"
