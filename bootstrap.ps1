# Bootstrap: clona il repo (pubblico) e avvia l'installazione su Windows.
#
#   irm https://raw.githubusercontent.com/vigliafg/noesis-pdf-cloner-service/main/bootstrap.ps1 | iex
#
# Oppure, dal repo clonato:
#   .\bootstrap.ps1 --ci --no-service --skip-warm
#
# Variabili: NOESIS_DIR (destinazione), NOESIS_REPO_URL (default: GitHub).
# Gli argomenti vengono inoltrati a install.ps1.
$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:NOESIS_REPO_URL) { $env:NOESIS_REPO_URL } else { "https://github.com/vigliafg/noesis-pdf-cloner-service.git" }
$Dest = if ($env:NOESIS_DIR) { $env:NOESIS_DIR } else { Join-Path $HOME "noesis-pdf-cloner-service" }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git non trovato. Installalo e riprova."
    exit 1
}

if (Test-Path (Join-Path $Dest ".git")) {
    Write-Host "· aggiorno $Dest"
    git -C $Dest pull --ff-only
} else {
    Write-Host "· clono in $Dest"
    git clone $RepoUrl $Dest
}

& (Join-Path $Dest "install.ps1") @args

# Propaga l'exit code solo quando eseguito come file (non sotto `iex`, dove
# `exit` chiuderebbe la sessione dell'utente).
if ($MyInvocation.MyCommand.Path) {
    exit $LASTEXITCODE
}
