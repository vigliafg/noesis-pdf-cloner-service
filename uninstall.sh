#!/usr/bin/env bash
# Disinstalla noesis-pdf-cloner-service (Linux · macOS · WSL).
#
#   ./uninstall.sh              scelta interattiva di cosa rimuovere
#   ./uninstall.sh --dry-run    mostra il piano senza modificare nulla
#   ./uninstall.sh --all -y     rimuove tutto (nessuna traccia del servizio)
#
# Vedi `./noesis uninstall --help` per tutte le opzioni.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/noesis" uninstall "$@"
