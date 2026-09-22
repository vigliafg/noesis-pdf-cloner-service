#!/usr/bin/env bash
# Noesis PDF Cloner — CLI headless (senza server).
#
#   ./run-cli.sh report.pdf -p 3,5,10-12 --dst it --engine bing --range-mode single
#   ./run-cli.sh *.pdf -p all --dst it --workers 2
#   ./run-cli.sh report.pdf --list-pages
set -e
cd "$(dirname "$0")"
exec ./noesis cli "$@"
