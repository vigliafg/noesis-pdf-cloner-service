#!/usr/bin/env bash
# Noesis PDF Cloner — Service: avvia SOLO l'API (nessun worker).
#
# Da usare insieme a uno o più `run-worker.sh`: i job vengono accodati qui e
# reclamati dai processi worker tramite la coda condivisa su SQLite.
set -e
cd "$(dirname "$0")"

export ROLE="${ROLE:-api}"
export HOST="${HOST:-0.0.0.0}"
exec ./noesis run "$@"
