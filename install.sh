#!/usr/bin/env bash
# Installa noesis-pdf-cloner-service (Linux · macOS · WSL).
#
#   ./install.sh                 installa e avvia il servizio
#   ./install.sh --no-service    solo setup (venv, motore, config)
#   ./install.sh --open-firewall apri la porta 18080 nel firewall
#   ./install.sh --skip-warm     non scaricare ora i modelli del motore
#
# Vedi `./noesis install --help` per tutte le opzioni.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/noesis" install "$@"
