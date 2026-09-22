#!/usr/bin/env bash
# Noesis PDF Cloner — Service: avvia il server in primo piano.
#
# Wrapper della console: `./noesis run` assicura venv e dipendenze e lancia
# uvicorn con un solo processo (coda e semafori del motore sono locali).
set -e
cd "$(dirname "$0")"
exec ./noesis run "$@"
