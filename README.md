# noesis-pdf-cloner-service

[![tests](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/tests.yml/badge.svg)](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/tests.yml)
[![docker](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/docker.yml/badge.svg)](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/docker.yml)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-noesis--pdf--cloner--service-2496ED?logo=docker&logoColor=white)](https://github.com/vigliafg/noesis-pdf-cloner-service/pkgs/container/noesis-pdf-cloner-service)
[![license: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

Servizio **server** e **CLI headless** della pipeline di
[noesis-pdf-cloner](https://github.com/vigliafg/noesis-pdf-cloner): apre un PDF,
traduce le pagine scelte **preservandone il layout** e le restituisce in un PDF
unico o in pagine singole (ZIP).

Motore: **[pdf2zh_next v2](https://github.com/PDFMathTranslate/PDFMathTranslate-next)**
(typesetter BabelDOC) con i tre motori di traduzione:

| Motore | Descrizione |
|---|---|
| `google` | catena gratuita (`dict-chrome-ex` → `translate-pa` → `gtx` → Microsoft → LLM) |
| `bing` | traduttore Bing built-in di pdf2zh_next |
| `llm` | LLM via OpenRouter (`OPENROUTER_API_KEY`) — usa il percorso "OpenAI-compatibile" (`--openai`) di pdf2zh; alias storico `openai` |

📐 **Documento tecnico delle scelte architetturali (implementate e future):
[`ARCHITETTURA.md`](ARCHITETTURA.md).**

## Stato

**Funzionante** (v0.1.0). Verificato end-to-end su un PDF reale (`ha22.pdf`,
4.132 pagine): upload, anteprima, stima, coda, traduzione, download — sia da
**server** sia da **CLI**. Motore `pdf2zh_next 2.9.0` (BabelDOC 0.6.2) in `.venv2`.
Test: **223 passed** (`pytest`, motore fittizio, nessuna rete). Disponibile anche
come **immagine Docker multi-arch** (vedi [Docker](#docker-immagine-pronta-multi-piattaforma)).

## Architettura

```
utente ─► FastAPI /api/v1 ─┬─ Documenti: upload, thumbnail, /PageLabels
                           └─ Job ─► coda a priorità (SQLite + worker thread)
                                        └─ pipeline.run_job
                                             ├─ blocchi di 100 pagine
                                             ├─ engine → pdf2zh_next (subprocess, .venv2)
                                             └─ cache versionata (split / tradotti)
CLI (noesis-cloner) ──────────────────────┘ stessa pipeline e stessa cache
```

## Caratteristiche

- **Frontend web**: upload drag&drop, selezione pagine (singola / intervallo /
  lista `3,5,10-12`), lingua origine e destinazione, motore, nome del PDF,
  e per gli intervalli **PDF unico** oppure **ZIP di pagine singole**.
- **Anteprima anti-errore**: miniatura della pagina (o della prima e ultima del
  range) con **numero fisico + etichetta stampata** (`/PageLabels`), per non
  confondere le due numerazioni dei PDF.
- **Log di esecuzione** per ogni job (JSONL) e **streaming live via SSE**.
- **Stima prima dell'avvio**: tempo (storico per motore + pagine in cache) e
  costo stimati, mostrati nel frontend e via `POST /jobs/estimate`.
- **Libri interi**: le pagine sono elaborate a blocchi da 100 (`MAX_PAGES_PER_BLOCK`).
- **Coda a priorità** e **multithreading**: pool di worker + parallelismo per
  pagina + limite globale sui processi `pdf2zh_next`.
- **Si adatta alla macchina (autosizing)** e **scala**: coda condivisa su DB,
  ruoli `api`/`worker` separabili, guardie RAM/disco. In **container** l'autosize
  legge i **limiti cgroup**.
- **Docker multi-arch** (`linux/amd64`, `linux/arm64`) su GHCR, **out-of-the-box**
  (motore e asset inclusi): Linux nativo, Windows/macOS via Docker Desktop.
- **CLI headless** con batch multi-PDF e barra `tqdm`, senza avviare il server.
- **Cache condivisa e versionata** (server e CLI riusano le stesse traduzioni).
- **Predisposto per il commerciale**: seam per autenticazione (Supabase/OIDC/
  reverse proxy), quote/usage e pagamenti Stripe; tabelle DB già presenti.

## Installazione (consigliata)

Un solo comando, multipiattaforma (**Linux · macOS · WSL · Windows nativo**):

```bash
git clone https://github.com/vigliafg/noesis-pdf-cloner-service
cd noesis-pdf-cloner-service
./install.sh
```

La console `noesis` crea i venv e il motore, scrive la configurazione, installa
il servizio (avvio automatico), chiede la chiave OpenRouter (opzionale) e la
verifica, attende che il servizio risponda sulla porta e stampa gli URL (locale +
LAN). A fine installazione stampa il **report completo di salute/preflight** e i
**link cliccabili**. Per la LAN, `--open-firewall` apre la porta limitandola alla
**sottorete locale**. Guida completa: [`docs/INSTALL.md`](docs/INSTALL.md).

Cruscotto quotidiano: `./noesis status` · `logs` · `doctor` · `open` ·
`start`/`stop`/`restart` · `bundle` (offline) · `update` · `uninstall`.

### Docker (immagine pronta, multi-piattaforma)

Alternativa all'installazione: un'**immagine multi-arch** (`linux/amd64`,
`linux/arm64`) pubblicata su GitHub Container Registry. Contiene **tutto** — i due
venv, il motore `pdf2zh_next` e gli **asset BabelDOC pre-scaricati** — quindi si
avvia subito, senza installare nulla.

```bash
docker run -d --name noesis -p 18080:18080 -v noesis-data:/data \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
# → http://localhost:18080
```

I motori **`google`** e **`bing`** funzionano subito (gratuiti). Il motore **`llm`**
richiede la chiave OpenRouter:

```bash
docker run -d --name noesis -p 18080:18080 -v noesis-data:/data \
  -e OPENROUTER_API_KEY="sk-or-..." \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```

#### Dove gira

| Sistema | Come | Immagine |
|---|---|---|
| **Linux** | Docker / Podman nativi | `linux/amd64`, `linux/arm64` |
| **Windows 10/11** | **Docker Desktop** (backend **WSL2**) | `linux/amd64` (o `arm64` su Windows on ARM) |
| **macOS** | Docker Desktop | `arm64` (Apple Silicon) / `amd64` (Intel) |

> È un'immagine **Linux**: su Windows/macOS gira nel kernel Linux di Docker
> Desktop. I **container Windows nativi non sono supportati** — per Windows senza
> Docker c'è l'installer nativo (`.\install.ps1`).

**Requisiti**: Docker Engine (Linux) oppure Docker Desktop con WSL2/Hyper-V
abilitati (Windows) o Docker Desktop (macOS); ~2 GB di spazio per l'immagine;
accesso a Internet in uscita (la traduzione contatta Google/Bing/OpenRouter).

#### Avvio rapido

Linux / macOS / WSL:

```bash
docker run -d --name noesis -p 18080:18080 -v noesis-data:/data \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```

Windows (PowerShell):

```powershell
docker run -d --name noesis -p 18080:18080 -v noesis-data:/data `
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```

Poi apri <http://localhost:18080>. La mappatura `-p 18080:18080` ascolta su tutte
le interfacce: per l'uso in **LAN** assicurati che il firewall dell'host consenta
la porta 18080.

#### Docker Compose

```bash
docker compose up -d          # usa il docker-compose.yml del repo
```

`docker-compose.yml` imposta porta, volume, `DATA_DIR` e (commentati) i limiti
`WORKERS`, `PAGE_CONCURRENCY`, `MAX_ENGINE_PROCS` e la `OPENROUTER_API_KEY`.

Per un deployment **API + worker** con limiti di risorse già pronti usa
[`docker-compose.prod.yml`](docker-compose.prod.yml):

```bash
docker compose -f docker-compose.prod.yml up -d
```

#### Dati e persistenza

- **`/data`** (volume): upload, cache traduzioni, artefatti, log e `jobs.db`.
  Usa un **volume nominato** (`-v noesis-data:/data`): è la scelta consigliata
  anche su Windows/macOS.
- Con un **bind mount** la cartella deve essere scrivibile dall'utente `noesis`
  (**uid 1000**): su Linux `sudo chown -R 1000:1000 <cartella>`. Su Docker
  Desktop preferisci i volumi nominati.
- Gli **asset del motore** sono già nell'immagine: nessun download alla prima
  traduzione (serve comunque la rete per tradurre).

#### Configurazione

Tutte le variabili della tabella
[Configurazione](#configurazione-variabili-dambiente) si passano con `-e NOME=valore`.
Le più usate nel container: `OPENROUTER_API_KEY`, `WORKERS`, `PAGE_CONCURRENCY`,
`MAX_ENGINE_PROCS`, `ROLE`, `WORKER_COUNT`, `MAX_UPLOAD_MB`.

#### Limiti di risorse e autosizing

L'autosize legge i **limiti del container** (cgroup), non le risorse dell'host:

```bash
docker run -d --cpus 2 --memory 4g -p 18080:18080 -v noesis-data:/data \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```

calcola i valori per 2 CPU / 4 GB. Per il controllo esplicito:
`-e WORKERS=2 -e PAGE_CONCURRENCY=2 -e MAX_ENGINE_PROCS=2` (o `-e AUTOSIZE=false`).

#### Scalare (API + worker)

```bash
# 1 API (accoda) + N worker (eseguono), stesso volume /data
docker run -d --name noesis-api -p 18080:18080 -v noesis-data:/data \
  -e ROLE=api -e UVICORN_WORKERS=2 ghcr.io/vigliafg/noesis-pdf-cloner-service:latest

for i in 1 2 3 4; do
  docker run -d --name "noesis-w$i" -v noesis-data:/data \
    -e ROLE=worker -e WORKER_COUNT=4 ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
done
```

#### Aggiornare e diagnosticare

```bash
docker pull ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
docker compose up -d            # ricrea con la nuova immagine (il volume resta)

docker exec noesis ./noesis doctor
docker exec noesis ./noesis logs -n 50
curl -s http://localhost:18080/api/v1/health
```

#### Problemi comuni

| Sintomo | Causa / rimedio |
|---|---|
| `address already in use` sulla 18080 | porta occupata → usa `-p 18081:18080` |
| `'/data' non è scrivibile` | bind mount non scrivibile da uid 1000 → `chown` o volume nominato |
| Il container non parte su Windows | Docker Desktop non avviato / WSL2 non abilitato |
| `engine_available: false` | immagine diversa: quella ufficiale include il motore |

Guida estesa (compose, build locale, pubblicazione su GHCR): [`docs/DOCKER.md`](docs/DOCKER.md).

### Disinstallazione

```bash
./uninstall.sh                 # (o ./noesis uninstall) scelta interattiva di cosa rimuovere
./noesis uninstall --dry-run   # mostra il piano con le dimensioni, senza toccare nulla
./noesis uninstall --data      # rimuove il servizio e i dati
./noesis uninstall --all -y    # nessuna traccia del servizio (venv + motore + dati + cache)
```

Senza argomenti, su terminale, `uninstall` mostra il menu **"Cosa rimuovere"**
(venv del servizio, motore `.venv2`, cache BabelDOC, dati, cache esterna) con le
dimensioni e chiede conferma; in un contesto non interattivo (pipe/CI) o con
`--json`/`--yes` è **conservativo** e rimuove solo il servizio. `--all` è
l'equivalente di "nessuna traccia". La **cache condivisa di `uv`/Python gestiti
non viene mai toccata** (non è nostra); il repository del codice non viene mai
rimosso.

### Avvio manuale (senza servizio)

Serve **Python 3.12** e [uv](https://docs.astral.sh/uv/).

```bash
./setup_engine.sh     # crea .venv2 e installa pdf2zh_next (motore)
./run.sh              # avvia il server su http://127.0.0.1:18080
```

Con `ROLE=all` (default di `run.sh`) il server **deve** girare con un solo
processo uvicorn (`--workers 1`): in quel processo coda e semafori del motore
sono locali e il parallelismo è interno (thread). Con la coda su **DB**
(predefinita) puoi invece separare API e worker — vedi "Scalabilità" più sotto.

### Deployment scalabile (API + worker)

```bash
ROLE=api ./run-api.sh                 # solo API: accoda i job (1..N processi)
WORKER_COUNT=4 ./run-worker.sh        # un processo worker (avviarne N)
```

Con `ROLE=api` l'API non esegue job: i **worker** li reclamano dalla coda
condivisa su SQLite (`DATA_DIR` comune). File systemd/nginx in
[`deploy/`](deploy/README.md).

### CLI headless (senza server)

```bash
./run-cli.sh pdfs/ha22.pdf -p 100-103 --src en --dst it --engine google \
    --output ha22_it --range-mode merged

./run-cli.sh pdfs/report.pdf -p 3,5,10-12 --engine bing --dst it \
    --output report_it --range-mode single --out-dir ./out

./run-cli.sh pdfs/*.pdf -p all --dst it --engine google --workers 2

./run-cli.sh pdfs/ha22.pdf --list-pages  # indice fisico → etichetta stampata
./run-cli.sh --check                     # verifica il motore
./run-cli.sh --doctor                    # diagnostica completa (motore, uv, chiave, modello)
```

`--doctor` esegue la diagnostica **runtime** (ambiente, `uv`, `pdf2zh_next`,
rete, chiave OpenRouter, modello LLM, catena gratuita) e fa da exit code
`0` = ok, `1` = avvisi, `2` = errori bloccanti.

> Non va confuso con **`./noesis doctor`** (`tools/noesis.py`), che diagnostica
> l'**installazione** (venv servizio/motore, config, cartella dati, spazio,
> firewall, server raggiungibile). I due sono complementari: l'installer dice se
> il software è installato bene, `noesis-cloner --doctor` dice se è pronto a
> **tradurre** (motore, chiave, modello).

I **PDF di test** stanno in `pdfs/` (non versionati: vedi `pdfs/README.md`).

Opzioni principali: `-p/--pages` (`all`, `7`, `100-103`, `3,5,10-12`), `--src`,
`--dst`, `--engine`, `-o/--output`, `--out-dir`, `--range-mode merged|single`,
`--pages-concurrency`, `--max-procs`, `--workers`, `--cache-dir`, `--force`,
`--log-json`, `-v`, `--list-langs`, `--list-engines`, `--list-pages`.
Exit code: `0` ok, `1` fallimenti parziali, `2` errore fatale.

Installando il pacchetto (`pip install -e .`) è disponibile anche il comando
`noesis-cloner`.

## API

Base: `/api/v1`. Esempi con `curl`:

```bash
# 1) carica il PDF (ritorna doc_id, page_count, etichette)
curl -s -F "file=@pdfs/ha22.pdf" http://127.0.0.1:18080/api/v1/documents

# 2) anteprima di una pagina (PNG)
curl -s "http://127.0.0.1:18080/api/v1/documents/<doc_id>/thumb?page=155&w=200" -o p156.png

# 3) crea il job
curl -s -X POST http://127.0.0.1:18080/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"doc_id":"<doc_id>","pages":"156-159","src_lang":"en","dst_lang":"it",
       "engine":"google","output_name":"ha22_it","range_mode":"merged"}'

# 4) stato e log live
curl -s http://127.0.0.1:18080/api/v1/jobs/<job_id>
curl -N http://127.0.0.1:18080/api/v1/jobs/<job_id>/events

# 5) download
curl -sOJ http://127.0.0.1:18080/api/v1/jobs/<job_id>/download
```

Endpoint (prefisso `/api/v1`): `POST/GET/DELETE /api/v1/documents`,
`GET /api/v1/documents/{id}/thumb`, `POST /api/v1/jobs`,
`POST /api/v1/jobs/estimate`, `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`,
`GET /api/v1/jobs/{id}/events`, `GET /api/v1/jobs/{id}/download`,
`POST /api/v1/jobs/{id}/cancel`, `GET /api/v1/meta`, `GET /api/v1/system`,
`GET /api/v1/health`, `GET /api/v1/metrics`.

`GET /api/v1/health` è **economico**: `engine_available`, `engine_runnable`,
`key_present`, `queue_length`, `workers`, `role` e `status`
(`ok`/`degraded`). Con **`?deep=1`** esegue la diagnostica completa (rete,
chiave, modello, catena gratuita) e la espone in `checks` (usa `0`/`1`/`2` come
`--doctor`): è lo stesso motore di `app/diagnostics.py`.

Un job con `engine="llm"` e nessuna `OPENROUTER_API_KEY` viene rifiutato a monte
con **409** (guardia `PREFLIGHT_GUARD`, attiva di default) invece di fallire in
coda.

### Stima

```bash
# stima tempo/costo di una selezione (prima di inviare il job)
curl -s -X POST http://127.0.0.1:18080/api/v1/jobs/estimate \
  -H 'Content-Type: application/json' \
  -d '{"doc_id":"<doc_id>","pages":"200-206","engine":"google","dst_lang":"it"}'
```

## Stima del costo (motore LLM)

Per il motore `llm` il costo è stimato dal testo sorgente con l'equazione
**calibrata empiricamente** su una traduzione reale (Mercury-2.5, 15 pagine):

```
token_in  = (chars_sorgente / 4) * 13.3       # 13.3 = fattore overhead (prompt/chunk)
token_out = token_in * 1.09                    # caratteri tradotti / sorgente
costo_USD = token_in/1e6 * 0.04 + token_out/1e6 * 0.15

# in forma compatta (per pagina):
costo_USD_pagina ≈ 6.8e-7 * chars_sorgente      # ≈ 0.0054 $ per una pagina da ~8.000 char
```

Riferimento misurato: range 2656–2670 (15 pagine, ~7.924 char/pagina) → spend
OpenRouter **$0.08057** totali, cioè **~$0.00537/pagina** (la stima "naive"
senza overhead dava $0.00040, ~13× in meno). I parametri sono configurabili
(`LLM_PRICE_*`, `LLM_OVERHEAD_FACTOR`, `LLM_OUTPUT_RATIO`, `CHARS_PER_TOKEN`).

## Scalabilità e autoadattamento

- **Autosizing** (`AUTOSIZE=true`): alla partenza il servizio rileva CPU, RAM
  disponibile e disco e calcola `workers`, `page_concurrency`, `max_engine_procs`.
  Con `ROLE=worker WORKER_COUNT=N` le risorse sono **divise per N**, così il
  totale dei processi motore resta limitato. Le env esplicite vincono sempre.
- **Guardie**: se disco/RAM scendono sotto soglia (`MIN_FREE_DISK_MB`,
  `MIN_FREE_RAM_MB`) le nuove richieste di job ricevono `503`.
- **Coda su DB** (`QUEUE_BACKEND=db`): 1 processo **API** + N **worker** sullo
  stesso VPS (o più, con `DATA_DIR` condiviso), senza dipendenze esterne.
- **Stato e capacità**: `GET /api/v1/system` riporta risorse, valori effettivi e
  consigliati, lunghezza coda.
- **Verticale**: ridimensioni il VPS e riavvii → i limiti si ricalcolano.
- **Orizzontale**: aumenti `WORKER_COUNT` e avvii altre unità worker.

## Configurazione (variabili d'ambiente)

Le stesse variabili si possono impostare nel file **`<data_dir>/noesis.env`**
(creato da `./noesis install`): è il posto unico da modificare. Precedenza:
opzione CLI > variabile della shell > `noesis.env` > default.

All'installazione la console chiede la **chiave OpenRouter** (opzionale, solo
motore `llm`) con input **nascosto**; `noesis.env` è scritto con permessi `0600`.
Subito dopo verifica **chiave, credito e modello** (stessi check di
`/api/v1/health?deep=1`). In modalità non interattiva non chiede nulla: imposta
`OPENROUTER_API_KEY` in `noesis.env` (o nell'ambiente) e riavvia con
`./noesis restart`.

| Variabile | Default | Descrizione |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `18080` | bind del server |
| `DATA_DIR` | `./data` | dati (upload, DB, log, artefatti) |
| `CACHE_ROOT` | `<DATA_DIR>/cache` | cache di split/traduzioni (condivisa con la CLI) |
| `AUTOSIZE` | `true` | adatta workers/concorrenza/processi alla macchina |
| `ROLE` | `all` | `all` \| `api` (solo accodo) \| `worker` (esegue) |
| `WORKER_COUNT` | `1` | numero totale di processi worker (divide le risorse) |
| `QUEUE_BACKEND` | `db` | `db` (multi-processo) \| `memory` (singolo processo) |
| `WORKERS` | auto | thread worker della coda (0 = autosize) |
| `PAGE_CONCURRENCY` | auto | pagine tradotte in parallelo per job (0 = autosize) |
| `MAX_ENGINE_PROCS` | auto | processi `pdf2zh_next` simultanei (0 = autosize) |
| `ENGINE_MEMORY_MB` | `800` | RAM stimata per processo motore (per l'autosizing) |
| `MIN_FREE_DISK_MB` | `1024` | soglia disco: sotto, i nuovi job ricevono 503 |
| `MIN_FREE_RAM_MB` | `512` | soglia RAM disponibile: sotto, 503 |
| `MAX_UPLOAD_MB` | `500` | dimensione massima upload |
| `MAX_QUEUE_SIZE` | `100` | job in coda prima di rispondere 429 |
| `MAX_PAGES_PER_BLOCK` | `100` | pagine elaborate per blocco (il job può coprire l'intero libro) |
| `MAX_PAGES_TOTAL` | `5000` | pagine massime richiedibili in un job |
| `ESTIMATE_MS_PER_PAGE_GOOGLE` / `_BING` / `_LLM` | `0` | override stima ms/pagina (`0` = storico/default; alias `_OPENAI`) |
| `COST_CENTS_PER_PAGE_GOOGLE` / `_BING` / `_LLM` | `0` / `0` / `1` | prezzo per pagina in centesimi (LLM: 1 = commerciale; 0 = usa l'equazione; alias `_OPENAI`) |
| `LLM_PRICE_PROMPT_PER_MTOK` | `0.04` | prezzo prompt LLM (USD per milione di token) |
| `LLM_PRICE_COMPLETION_PER_MTOK` | `0.15` | prezzo completion LLM (USD per milione di token) |
| `LLM_OVERHEAD_FACTOR` | `13.3` | fattore overhead dei prompt/chunk (calibrato) |
| `LLM_OUTPUT_RATIO` | `1.09` | caratteri tradotti / caratteri sorgente |
| `CHARS_PER_TOKEN` | `4.0` | caratteri per token |
| `ESTIMATE_SAMPLE_PAGES` | `12` | pagine campionate per stimare i caratteri |
| `JOB_RETENTION_HOURS` | `72` | retention di artefatti e log |
| `DOCUMENT_RETENTION_HOURS` | `24` | retention dei documenti non usati |
| `PDF2ZH_BIN` | auto | percorso dell'eseguibile `pdf2zh_next` |
| `OPENROUTER_API_KEY` | — | necessaria per il motore `llm` |
| `PDF_LLM_MODEL` / `PDF_LLM_BASE_URL` | `inception/mercury-2.5` / OpenRouter | modello LLM |
| `PREFLIGHT_GUARD` | `true` | rifiuta (409) un job `llm` senza chiave invece di accodarlo |
| `AUTH_MODE` | `none` | seam auth: `none` \| `proxy` \| `jwt` |
| `TRUSTED_PROXY_HEADERS` | `false` | fidati degli header del reverse proxy |
| `QUOTA_ENABLED` / `FEATURE_OCR` / `FEATURE_PAYMENTS` | `false` | seam commerciali |
| `RATE_LIMIT_PER_MINUTE` | `120` | rate limit per attore |

## Test

```bash
.venv/bin/python -m pytest -q
```

I test usano un **motore fittizio** (nessuna rete, nessun `pdf2zh_next`).
La CI (`.github/workflows/tests.yml`) esegue i test su **Linux, macOS e Windows**,
prova l'installer end-to-end (`noesis install --no-engine` + `doctor`) e su Windows
verifica il **servizio** (Task Scheduler), il **firewall scoped** e i **log**.

## Struttura

```
app/
├── engine.py        split → pdf2zh_next → cache versionata (+ thumb/labels)
├── pipeline.py      CUORE condiviso server/CLI
├── cli.py           CLI headless (tqdm, batch)
├── queue.py         coda a priorità + worker (backend db/memory)
├── worker.py        runner del server
├── worker_main.py   processo worker standalone (multi-processo)
├── resources.py     rilevamento risorse e autosizing
├── storage.py       SQLite + percorsi filesystem
├── models.py        modelli API/persistenza
├── pages.py         parsing specifica pagine
├── pagelabels.py    espansione /PageLabels
├── auth.py          seam identità (anonimo ora)
├── quota.py         seam quota/usage
├── ocr.py           seam OCR
├── sse.py           streaming SSE
├── janitor.py       retention
├── metrics.py       metriche Prometheus
├── api/v1/          route versionate
├── templates/ static/  frontend
└── gtranslate_cli.py   catena gratuita per l'engine google
```

## Note e limiti

- **Scalabilità**: con `QUEUE_BACKEND=db` (predefinito) la coda è su SQLite e si
  possono avviare **1 API + N worker**. Con `QUEUE_BACKEND=memory` resta
  single-process (un solo uvicorn). Per più nodi serve `DATA_DIR` condiviso.
- **Motore e licenze**: `pdf2zh_next`/BabelDOC sono copyleft (AGPL, da
  verificare) e la catena Google usa endpoint non ufficiali. Prima di un uso
  commerciale valutare licenze e termini d'uso (vedi `HANDOFF.md`).
- **OCR**: le pagine scansionate senza testo non producono output; il seam OCR
  (`FEATURE_OCR`) le segnala nel log.
- Il frontend funziona anche senza PDF.js (anteprima via server); PDF.js locale
  è opzionale (`app/static/vendor/pdfjs/`).
