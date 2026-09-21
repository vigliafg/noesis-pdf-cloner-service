# Handoff — noesis-pdf-cloner-service

*Data: 2026-09-21 · Versione 0.1.0 · Repository pubblico:
`git@github.com:vigliafg/noesis-pdf-cloner-service.git` (SSH, branch `main`).*

Servizio **server + CLI headless** derivato da `noesis-pdf-cloner`: traduce PDF
preservando il layout (pdf2zh_next v2 / BabelDOC) con frontend web, coda a
priorità e parallelismo a livello pagina.

---

## 1. Stato

**Implementato e testato** (50 test, motore fittizio, nessuna rete):

- Pipeline condivisa `engine.py` + `pipeline.py` (server e CLI).
- Frontend web (Jinja2 + JS vanilla + SSE) con **anteprima anti-errore**
  (miniatura prima/ultima del range, numero fisico + etichetta `/PageLabels`).
- API `/api/v1`: documenti, thumbnail, job, log SSE, download, cancel, meta,
  health, metrics.
- Coda a priorità con recovery da SQLite, worker thread, backpressure.
- Cache **versionata**, scritture atomiche, lock inter-processo, process group
  per il cancel.
- CLI headless batch con `tqdm`.
- **Libri interi a blocchi da 100**, **stima tempo/costo** (`POST /jobs/estimate`)
  e **job notturni** (`start_at`, stato `scheduled` promosso dallo scheduler).
- **Modello di costo LLM calibrato**: `costo_USD ≈ 6.8e-7 × chars_sorgente`
  (overhead 13.3×, prezzi Mercury-2.5 0.04/0.15 $/Mtok). Vedi README.
- Retention (`janitor`), metriche Prometheus, seam per auth/quota/OCR/email/audit.

## 2. Scelte tecniche

1. **Una pipeline, due frontend**: `pipeline.run_job` è usato da `worker.py`
   (server) e da `cli.py`. Nessuna dipendenza FastAPI nella pipeline.
2. **SQLite = fonte di verità**: la coda in memoria si ricostruisce all'avvio
   (`running → interrupted`, `queued → ri-accodati`).
3. **Un solo processo uvicorn** (`--workers 1`): coda e semafori sono in
   memoria; il parallelismo è a thread. `QueueBackend` è astratto per un
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
| `pytest -q` | **60 passed** |
| Import/avvio uvicorn | `health` 200, `engine_available` true |
| Frontend | pagina `/` 200, meta popolato |
| CLI | `--version`, `--list-engines`, `--list-pages`, end-to-end con motore fittizio |

## 4. Limiti noti / TODO

1. **pdf2zh_next non testato end-to-end qui**: va installato con
   `./setup_engine.sh`; primo run lento (download modelli). Benchmark costi da fare.
2. **Licenze**: `pdf2zh_next`/BabelDOC copyleft (AGPL, da verificare) e catena
   Google con endpoint non ufficiali → **blocco da sciogliere prima del
   commerciale**. Spike legale + costi pianificati.
3. **OCR assente**: le scansioni senza testo non producono output; seam pronto.
4. **PDF.js opzionale**: l'anteprima usa il server; per il rendering client
   locale va collocata la build in `app/static/vendor/pdfjs/`.
5. **Singolo nodo**: la coda è in-process; per scalare serve un `QueueBackend`
   esterno (Redis) e un rate limit condiviso.
6. **Auth/pagamenti**: da implementare sopra i seam (Supabase/OIDC/proxy;
   Stripe Checkout + webhook + quota su `usage`).

## 5. Comando rapido

```bash
cd /home/vigliafg/Documenti/GitHub/noesis-pdf-cloner-service
uv pip install --python .venv/bin/python -q -r requirements.txt pytest httpx
.venv/bin/python -m pytest -q
./run.sh          # server
./run-cli.sh --help
```
