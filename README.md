# noesis-pdf-cloner-service

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
| `openai` | LLM via OpenRouter (`OPENROUTER_API_KEY`) |

## Stato

**Funzionante** (v0.1.0). Verificato end-to-end su un PDF reale (`ha22.pdf`,
4.132 pagine): upload, anteprima, stima, coda, traduzione, download — sia da
**server** sia da **CLI**. Motore `pdf2zh_next 2.9.0` (BabelDOC 0.6.2) in `.venv2`.
Test: **61 passed** (`pytest`, motore fittizio, nessuna rete).

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
- **Job notturni**: avvio programmato (`start_at`); la coda promuove
  automaticamente i job quando arriva l'ora.
- **Libri interi**: le pagine sono elaborate a blocchi da 100 (`MAX_PAGES_PER_BLOCK`).
- **Coda a priorità** e **multithreading**: pool di worker + parallelismo per
  pagina + limite globale sui processi `pdf2zh_next`.
- **Si adatta alla macchina (autosizing)** e **scala**: coda condivisa su DB,
  ruoli `api`/`worker` separabili, guardie RAM/disco.
- **CLI headless** con batch multi-PDF e barra `tqdm`, senza avviare il server.
- **Cache condivisa e versionata** (server e CLI riusano le stesse traduzioni).
- **Predisposto per il commerciale**: seam per autenticazione (Supabase/OIDC/
  reverse proxy), quote/usage e pagamenti Stripe; tabelle DB già presenti.

## Avvio rapido

Serve **Python 3.12** e [uv](https://docs.astral.sh/uv/).

```bash
./setup_engine.sh     # crea .venv2 e installa pdf2zh_next (motore)
./run.sh              # avvia il server su http://127.0.0.1:18080
```

Il server **deve** girare con un solo processo uvicorn (`run.sh` lo fa già):
la coda e i semafori del motore sono in memoria; il parallelismo è interno.
Con la coda su **DB** (predefinita) puoi invece separare API e worker — vedi
"Scalabilità" più sotto.

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
./run-cli.sh ha22.pdf -p 100-103 --src en --dst it --engine google \
    --output ha22_it --range-mode merged

./run-cli.sh report.pdf -p 3,5,10-12 --engine bing --dst it \
    --output report_it --range-mode single --out-dir ./out

./run-cli.sh *.pdf -p all --dst it --engine google --workers 2

./run-cli.sh ha22.pdf --list-pages       # indice fisico → etichetta stampata
./run-cli.sh --check                     # verifica il motore
```

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
curl -s -F "file=@ha22.pdf" http://127.0.0.1:18080/api/v1/documents

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

Endpoint: `POST/GET/DELETE /documents`, `GET /documents/{id}/thumb`,
`POST /jobs`, `POST /jobs/estimate`, `GET /jobs`, `GET /jobs/{id}`,
`GET /jobs/{id}/events`, `GET /jobs/{id}/download`, `POST /jobs/{id}/cancel`,
`GET /meta`, `GET /system`, `GET /health`, `GET /metrics`.

### Stima e avvio programmato

```bash
# stima tempo/costo di una selezione (prima di inviare il job)
curl -s -X POST http://127.0.0.1:18080/api/v1/jobs/estimate \
  -H 'Content-Type: application/json' \
  -d '{"doc_id":"<doc_id>","pages":"200-206","engine":"google","dst_lang":"it"}'

# job notturno: avvia tra due ore
curl -s -X POST http://127.0.0.1:18080/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"doc_id":"<doc_id>","pages":"1-120","engine":"google","start_at":"2026-09-21T23:00:00Z"}'
```

## Stima del costo (motore LLM)

Per il motore `openai` il costo è stimato dal testo sorgente con l'equazione
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
| `SCHEDULE_POLL_SECONDS` | `30` | frequenza del pianificatore (job notturni) |
| `ESTIMATE_MS_PER_PAGE_GOOGLE` / `_BING` / `_OPENAI` | `0` | override stima ms/pagina (`0` = storico/default) |
| `COST_CENTS_PER_PAGE_GOOGLE` / `_BING` / `_OPENAI` | `0` / `0` / `1` | prezzo per pagina in centesimi (LLM: 1 = commerciale; 0 = usa l'equazione) |
| `LLM_PRICE_PROMPT_PER_MTOK` | `0.04` | prezzo prompt LLM (USD per milione di token) |
| `LLM_PRICE_COMPLETION_PER_MTOK` | `0.15` | prezzo completion LLM (USD per milione di token) |
| `LLM_OVERHEAD_FACTOR` | `13.3` | fattore overhead dei prompt/chunk (calibrato) |
| `LLM_OUTPUT_RATIO` | `1.09` | caratteri tradotti / caratteri sorgente |
| `CHARS_PER_TOKEN` | `4.0` | caratteri per token |
| `ESTIMATE_SAMPLE_PAGES` | `12` | pagine campionate per stimare i caratteri |
| `JOB_RETENTION_HOURS` | `72` | retention di artefatti e log |
| `DOCUMENT_RETENTION_HOURS` | `24` | retention dei documenti non usati |
| `PDF2ZH_BIN` | auto | percorso dell'eseguibile `pdf2zh_next` |
| `OPENROUTER_API_KEY` | — | necessaria per il motore `openai` |
| `PDF_LLM_MODEL` / `PDF_LLM_BASE_URL` | `inception/mercury-2.5` / OpenRouter | modello LLM |
| `AUTH_MODE` | `none` | seam auth: `none` \| `proxy` \| `jwt` |
| `TRUSTED_PROXY_HEADERS` | `false` | fidati degli header del reverse proxy |
| `QUOTA_ENABLED` / `FEATURE_OCR` / `FEATURE_PAYMENTS` | `false` | seam commerciali |
| `RATE_LIMIT_PER_MINUTE` | `120` | rate limit per attore |

## Test

```bash
.venv/bin/python -m pytest -q
```

I test usano un **motore fittizio** (nessuna rete, nessun `pdf2zh_next`).

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
