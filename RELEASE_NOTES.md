# Noesis PDF Cloner Service 0.1.12

Server **API + web UI** e **CLI headless** della pipeline di
[noesis-pdf-cloner](https://github.com/vigliafg/noesis-pdf-cloner), allineato al
desktop **0.1.12**.

## Novità

- **Allineamento motore**: aggiunti i flag desktop mancanti
  `--openai-timeout` (90 s), `--no-auto-extract-glossary` e
  `--pool-max-workers` (anche senza fast engine); `QPS_GOOGLE`/`QPS_BING`
  configurabili.
- **Preset `normal`/`fast`/`fastest`** applicano davvero modello LLM, pool,
  reasoning e prompt come il desktop. Una variabile d'ambiente esplicita vince.
- **Contratto di parità** con `ENGINE_SOURCE.json` e
  `tests/test_desktop_parity.py` (flag, default, motori, preset).
- **334 test** verdi (motore fittizio, nessuna rete).
- **Release** con CLI standalone Windows/Linux/macOS, wheel/sdist e immagine
  Docker **multi-arch** su GHCR.

## Asset

| Canale | Piattaforma | File |
| --- | --- | --- |
| GitHub Release | Windows x64 | `noesis-pdf-cloner-service-windows-x64.zip` |
| GitHub Release | Linux x86_64 | `noesis-pdf-cloner-service-linux-x86_64.tar.gz` |
| GitHub Release | macOS x64 / arm64 | `…-macos-x64.tar.gz`, `…-macos-arm64.tar.gz` |
| GitHub Release | Python | wheel + sdist |
| GHCR | linux/amd64, linux/arm64 | `ghcr.io/vigliafg/noesis-pdf-cloner-service:0.1.12` |
| Integrità | — | `SHA256SUMS.txt` |

## Verifica

```bash
sha256sum -c SHA256SUMS.txt
tar -xzf noesis-pdf-cloner-service-linux-x86_64.tar.gz
./noesis-cloner --version      # 0.1.12
./noesis-cloner --help
docker run --rm ghcr.io/vigliafg/noesis-pdf-cloner-service:0.1.12 --version
```

> I bundle standalone contengono la **CLI**. Il server si esegue da checkout,
> `pip install` o immagine Docker. Il motore `pdf2zh_next` resta esterno
> (`./setup_engine.sh`) ed è già incluso nell'immagine Docker.

## Requisiti

- Windows 10+, macOS 12+, oppure Linux x86_64.
- Motore `pdf2zh_next` 2.9.0 (installato da `./setup_engine.sh` o dal container).
- `OPENROUTER_API_KEY` solo per il motore `llm`.

Vedi il [README](https://github.com/vigliafg/noesis-pdf-cloner-service#readme)
per installazione, API, configurazione e preset.
