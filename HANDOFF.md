# Handoff — noesis-pdf-cloner-service

*Data: 2026-09-24 · Versione 0.1.0 · Repository pubblico:
`git@github.com:vigliafg/noesis-pdf-cloner-service.git` (SSH, branch `main`).*

Servizio **server + CLI headless** derivato da `noesis-pdf-cloner`: traduce PDF
preservando il layout (pdf2zh_next v2 / BabelDOC) con frontend web, coda a
priorità e parallelismo a livello pagina.

---

## 1. Stato

**Implementato e testato** (223 test, motore fittizio, nessuna rete):

- Pipeline condivisa `engine.py` + `pipeline.py` (server e CLI).
- **Console `noesis`** (`tools/noesis.py`, sola stdlib, multipiattaforma):
  installazione guidata (venv, motore, config, servizio, pre-warm), gestione
  (`start/stop/status/logs/doctor/open`), **bundle offline**, servizio
  systemd-user/launchd/Task Scheduler, `--mode user|system` per il futuro VPS.
  Gusci `install.sh` / `install.ps1` / `bootstrap.sh`; launcher `./noesis`.
  Vedi `docs/INSTALL.md`.
- Frontend web (Jinja2 + JS vanilla + SSE) con **anteprima anti-errore**
  (miniatura prima/ultima del range, numero fisico + etichetta `/PageLabels`).
- API `/api/v1`: documenti, thumbnail, job, log SSE, download, cancel, meta,
  health, metrics.
- Coda a priorità con recovery da SQLite, worker thread, backpressure.
- Cache **versionata**, scritture atomiche, lock inter-processo, process group
  per il cancel.
- CLI headless batch con `tqdm`.
- **Libri interi a blocchi da 100** e **stima tempo/costo**
  (`POST /jobs/estimate`).
- **Modello di costo LLM calibrato**: `costo_USD ≈ 6.8e-7 × chars_sorgente`
  (overhead 13.3×, prezzi Mercury-2.5 0.04/0.15 $/Mtok). Vedi README.
- **Prezzo commerciale di default: 1 centesimo/pagina** per il motore LLM
  (`COST_CENTS_PER_PAGE_LLM=1`, in EUR); google/bing restano gratuiti.
- **Autosizing e scalabilità**: `resources.py` calcola worker/concorrenza/processi
  dalla macchina; coda su **DB** (`QUEUE_BACKEND=db`) con ruoli `ROLE=api|worker`
  e `WORKER_COUNT=N` (risorse divise tra i worker); guardie RAM/disco; endpoint
  `GET /system`. Deploy systemd/nginx in `deploy/`.
- **Docker multi-arch** (`linux/amd64`, `linux/arm64`) pubblicato su **GHCR**
  dalla CI: immagine con i due venv e gli asset BabelDOC pre-scaricati,
  `docker run` out-of-the-box; `resources.py` è **cgroup-aware** (autosize
  corretto nei container). Vedi `docs/DOCKER.md` / ADR-017.
- Retention (`janitor`), metriche Prometheus, seam per auth/quota/OCR/email/audit.

## 2. Scelte tecniche

1. **Una pipeline, due frontend**: `pipeline.run_job` è usato da `worker.py`
   (server) e da `cli.py`. Nessuna dipendenza FastAPI nella pipeline.
2. **SQLite = fonte di verità**: la coda si ricostruisce all'avvio dal DB
   (`running → interrupted`, `queued → ri-accodati`).
3. **Coda su DB, ruoli separabili**: il backend predefinito è SQLite
   (`QUEUE_BACKEND=db`) con claim atomico, quindi si possono eseguire 1 processo
   API + N worker (`ROLE=api|worker`, `WORKER_COUNT=N`); `QUEUE_BACKEND=memory`
   resta disponibile per il single-process. `QueueBackend` è astratto per un
   futuro Redis/Celery.
4. **Due livelli di parallelismo**: `ThreadPoolExecutor` per pagina
   (`PAGE_CONCURRENCY`) + `Semaphore` sui processi `pdf2zh_next`
   (`MAX_ENGINE_PROCS`, per processo).
5. **Cache versionata**: `cs<schema>-e<versione>[-<hash modello>]`; chiave =
   SHA-256 del contenuto; scritture tmp + `os.replace`; `flock` per i processi
   concorrenti (server + CLI condividono `CACHE_ROOT`).
6. **Cancel**: subprocess in una nuova sessione e `killpg` del gruppo.
7. **Seam commerciali no-op**: `auth.get_current_actor`, `quota.check_quota`,
   `ocr`, `emailer`, `audit`, tabelle `plans/subscriptions/entitlements/
   api_keys/teams/stripe_events` già migrate.

## 3. Verifiche

| Verifica | Esito |
|---|---|
| `pytest -q` | **223 passed** |
| Installer end-to-end (`noesis install --no-engine` + `doctor`) | ok |
| CI matrix (Linux · macOS · Windows) | test + installer |
| Docker: build multi-arch + smoke test | ok (CI, GHCR **pubblico**) |
| Docker: pull anonimo + avvio + traduzione google | health ok, 1/1 pagina |
| Import/avvio uvicorn | `health` e `/system` 200, `engine_available` true |
| Frontend | pagina `/` 200, meta popolato |
| CLI | `--version`, `--list-engines`, `--list-pages`, end-to-end con motore fittizio |
| Multi-processo | job accodato con `ROLE=api`, eseguito da `ROLE=worker` (coda su DB) |

## 4. Limiti noti / TODO

1. **pdf2zh_next**: validato end-to-end nel container (motore google, 1 pagina).
   Restano benchmark costi e collaudo LLM reale.
2. **Installer (`noesis`)**: collaudato su Linux; macOS/Windows girano in CI
   (test + installer `--no-engine`). Resta il **collaudo reale** su macOS e
   Windows nativo e del **bundle offline** end-to-end. Su Windows il cancel
   termina ora l'albero del motore (`taskkill /T /F`); da verificare font e lock
   cache (su Windows `flock` è no-op: ok single-process).
3. **Licenze**: `pdf2zh_next`/BabelDOC/PyMuPDF sono **AGPL-3.0**; aggiunti
   `LICENSE` (AGPL-3.0) e `NOTICE`. La catena Google usa endpoint non ufficiali →
   **blocco da sciogliere prima del commerciale**. Spike legale + costi pianificati.
4. **OCR assente**: le scansioni senza testo non producono output; seam pronto.
5. **PDF.js opzionale**: l'anteprima usa il server; per il rendering client
   locale va collocata la build in `app/static/vendor/pdfjs/`.
6. **Scalabilità**: coda su DB con ruoli `api`/`worker` (multi-processo sullo
   stesso VPS). Per **più nodi** serve `DATA_DIR` condiviso; un backend Redis
   resta l'evoluzione futura.
7. **Auth/pagamenti**: da implementare sopra i seam (Supabase/OIDC/proxy;
   Stripe Checkout + webhook + quota su `usage`).
8. **VPS esterno**: console già predisposta (`--mode system`); deploy con
   nginx/TLS/auth resta una fase successiva.

## 5. Comando rapido

```bash
cd /home/vigliafg/Documenti/GitHub/noesis-pdf-cloner-service
uv pip install --python .venv/bin/python -q -r requirements.txt pytest httpx
.venv/bin/python -m pytest -q
./install.sh             # installazione guidata (venv, motore, servizio)
./noesis doctor          # diagnosi
./noesis status|logs     # gestione
./run.sh                 # server (all: API + worker nello stesso processo)
./run-api.sh             # solo API (ROLE=api)
./run-worker.sh          # un processo worker (WORKER_COUNT=N)
./run-cli.sh --help
```

Docker:

```bash
docker run -d --name noesis -p 18080:18080 -v noesis-data:/data \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```
