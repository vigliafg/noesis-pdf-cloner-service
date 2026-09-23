# Disinstalla noesis-pdf-cloner-service su Windows (nativo).
#
#   .\uninstall.ps1                 scelta interattiva di cosa rimuovere
#   .\uninstall.ps1 --dry-run       mostra il piano senza modificare nulla
#   .\uninstall.ps1 --all -y        rimuove tutto (nessuna traccia del servizio)
#
# Se preferisci WSL, esegui invece `./uninstall.sh` dentro la distro Linux.
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir
& "$Dir\noesis.cmd" uninstall @args
exit $LASTEXITCODE
