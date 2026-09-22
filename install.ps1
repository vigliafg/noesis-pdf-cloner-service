# Installa noesis-pdf-cloner-service su Windows (nativo).
#
#   .\install.ps1
#   .\install.ps1 -NoService -SkipWarm
#
# Se preferisci WSL, esegui invece `./install.sh` dentro la distro Linux.
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir
& "$Dir\noesis.cmd" install @args
exit $LASTEXITCODE
