# Noesis PDF Cloner Service 0.2.1

Server **API + web UI**, **TUI** e **CLI headless** della pipeline di
[noesis-pdf-cloner](https://github.com/vigliafg/noesis-pdf-cloner), allineato al
desktop **0.2.1**.

## Novità

- **TUI allineata alle altre edizioni headless della famiglia**:
  - **selettore di file** (doppio clic, cartelle + solo `.pdf`) accanto al campo
    digitabile;
  - **tema** `auto|dark|light` (`--theme`, tasto `t` per cambiarlo al volo);
  - **interfaccia it/en** (`--lang`, default italiano);
  - **fallback a wizard a righe** quando Textual non è installato o il terminale
    è minimo (`TERM=dumb`, `--line`), con le stesse validazioni e lo stesso
    runner: il risultato è identico.
- **TUI interattiva** (dalla 0.2.0): Home dei lavori → 5 passi (file → pagine →
  lingue → motore → output) → esecuzione con avanzamento pagina per pagina, log
  e annullamento (`Esc`) → diagnostica. Client **locale e in-process**: stessi
  `Settings`, `noesis.env`, cache e SQLite del servizio, senza server né porta;
  con il server attivo la TUI non avvia job (evita la doppia esecuzione).
- **Anteprima anti-errore** nel terminale: numero fisico + etichetta
  `/PageLabels` della prima e dell'ultima pagina scelta, più le prime righe di
  testo (al posto delle miniature).
- **Fix del worker persistente** (dalla 0.2.0, condiviso col desktop):
  `engine_client.run()` è serializzata; senza, con più pagine in parallelo due
  thread potevano rubarsi le risposte e restare appesi fino a `page_timeout`
  (900 s).

## Verifica

- **387 test** (`pytest`, motore fittizio, nessuna rete), inclusi i test della
  TUI headless (Textual pilot), del wizard a righe e del client del worker.
- **e2e reali** con `pdf2zh_next`: 10 casi × 10 pagine (0.2.0) e **3 run × 5
  pagine** (0.2.1), service e desktop sugli stessi PDF/pagine, cache fredda;
  controlli su pagine, testo, traduzione effettiva, formato, lunghezza, italiano.
- Desktop allineato: **558 test** verdi.

## Asset

| Canale | Piattaforma | File |
| --- | --- | --- |
| GitHub Release | Windows x64 | `noesis-pdf-cloner-service-windows-x64.zip` |
| GitHub Release | Linux x86_64 | `noesis-pdf-cloner-service-linux-x86_64.tar.gz` |
| GitHub Release | macOS x64 / arm64 | `…-macos-x64.tar.gz`, `…-macos-arm64.tar.gz` |
| GitHub Release | Python | wheel + sdist |
| GHCR | linux/amd64, linux/arm64 | `ghcr.io/vigliafg/noesis-pdf-cloner-service:0.2.1` |
| Integrità | — | `SHA256SUMS.txt` |

## Verifica rapida

```bash
sha256sum -c SHA256SUMS.txt
tar -xzf noesis-pdf-cloner-service-linux-x86_64.tar.gz
./noesis-cloner --version      # 0.2.1
./noesis-cloner --help
docker run --rm --entrypoint noesis-cloner \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:0.2.1 --version
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
