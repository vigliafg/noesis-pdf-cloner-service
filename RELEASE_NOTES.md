# Noesis PDF Cloner Service 0.2.0

Server **API + web UI**, **TUI** e **CLI headless** della pipeline di
[noesis-pdf-cloner](https://github.com/vigliafg/noesis-pdf-cloner), allineato al
desktop **0.2.0**.

## Novità

- **TUI interattiva** (`./noesis` dal terminale, oppure `./noesis tui`):
  Home dei lavori → procedura guidata a 5 passi (file → pagine → lingue →
  motore → output) → esecuzione con avanzamento pagina per pagina, log e
  annullamento (`Esc`) → diagnostica. È un **client locale della stessa
  pipeline**: stessi `Settings`, `noesis.env`, cache e SQLite del servizio, ma
  **senza server** e senza porta; se il server è attivo la TUI non avvia job
  (evita la doppia esecuzione). Job `owner_id="tui"` con recovery dedicato.
- **Anteprima anti-errore anche nel terminale**: numero fisico + etichetta
  `/PageLabels` della prima e dell'ultima pagina scelta, più le prime righe di
  testo (sostituisce le miniature, che il terminale non può mostrare).
- **Dipendenze opzionali**: `requirements-tui.txt` (Textual) installate di
  default dall'installer (`--no-tui` per un'installazione solo servizio) e
  incluse nei bundle offline. **Non** entrano nell'immagine Docker.
- **Fix importante (condiviso col desktop)**: il client del worker persistente
  (`engine_client.py`) serializza `run()`. Senza, con più pagine in parallelo
  due thread potevano consumare la risposta dell'altro e restare appesi fino a
  `page_timeout` (900 s). Rilevato dagli e2e reali: ora 5 pagine con
  `PAGE_CONCURRENCY=2` passano in ~1 minuto invece di bloccarsi.
- **Refactoring**: `app/job_factory.py` centralizza la costruzione di engine +
  documento + job (usata da CLI e TUI).

## Verifica

- **368 test** (`pytest`, motore fittizio, nessuna rete), incluso il nuovo
  `tests/test_engine_client.py` che riproduce la corsa delle risposte.
- **10 casi e2e reali** da **10 pagine** ciascuno (PDF del corpus, motore
  `google`, cache fredda), con controllo del PDF prodotto: numero di pagine,
  testo presente su ogni pagina, testo **tradotto** (non copiato), formato
  identico all'originale, lunghezza plausibile, presenza di italiano.
- Desktop allineato: stessi 10 casi e2e e **558 test** verdi con il fix.

## Asset

| Canale | Piattaforma | File |
| --- | --- | --- |
| GitHub Release | Windows x64 | `noesis-pdf-cloner-service-windows-x64.zip` |
| GitHub Release | Linux x86_64 | `noesis-pdf-cloner-service-linux-x86_64.tar.gz` |
| GitHub Release | macOS x64 / arm64 | `…-macos-x64.tar.gz`, `…-macos-arm64.tar.gz` |
| GitHub Release | Python | wheel + sdist |
| GHCR | linux/amd64, linux/arm64 | `ghcr.io/vigliafg/noesis-pdf-cloner-service:0.2.0` |
| Integrità | — | `SHA256SUMS.txt` |

## Verifica rapida

```bash
sha256sum -c SHA256SUMS.txt
tar -xzf noesis-pdf-cloner-service-linux-x86_64.tar.gz
./noesis-cloner --version      # 0.2.0
./noesis-cloner --help
docker run --rm --entrypoint noesis-cloner \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:0.2.0 --version
```

> I bundle standalone contengono la **CLI**. Server e TUI si eseguono da
> checkout, `pip install` o immagine Docker (server). Il motore `pdf2zh_next`
> resta esterno (`./setup_engine.sh`) ed è già incluso nell'immagine Docker.

## Requisiti

- Windows 10+, macOS 12+, oppure Linux x86_64.
- Motore `pdf2zh_next` 2.9.0 (installato da `./setup_engine.sh` o dal container).
- `OPENROUTER_API_KEY` solo per il motore `llm`.

Vedi il [README](https://github.com/vigliafg/noesis-pdf-cloner-service#readme)
per installazione, API, TUI, configurazione e preset.
