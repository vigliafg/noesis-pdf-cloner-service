# Architettura — noesis-pdf-cloner-service

Documento tecnico delle **scelte architetturali**, di quelle **implementate** e
di quelle **previste** per le evoluzioni future. Versione 0.1.0.

Indice:

1. [Contesto e obiettivi](#1-contesto-e-obiettivi)
2. [Vista d'insieme](#2-vista-dinsieme)
3. [Componenti](#3-componenti)
4. [Ciclo di vita di un job](#4-ciclo-di-vita-di-un-job)
5. [Modello dati](#5-modello-dati)
6. [Decisions records (ADR)](#6-decisions-records-adr)
7. [Concorrenza e scalabilità](#7-concorrenza-e-scalabilità)
8. [Cache](#8-cache)
9. [Stima di tempo e costo](#9-stima-di-tempo-e-costo)
10. [Sicurezza](#10-sicurezza)
11. [Osservabilità e operazioni](#11-osservabilità-e-operazioni)
12. [Seam ed evoluzioni future](#12-seam-ed-evoluzioni-future)
13. [Limiti, rischi e debito tecnico](#13-limiti-rischi-e-debito-tecnico)
14. [Strategia di test](#14-strategia-di-test)
15. [Roadmap](#15-roadmap)

---

## 1. Contesto e obiettivi

`noesis-pdf-cloner` è un'app desktop PyQt6 che clona una pagina PDF traducendola
**preservandone il layout** tramite `pdf2zh_next` v2 (typesetter BabelDOC).
Questo repository ne è la **versione server + CLI headless**, pensata per:

- servire più utenti contemporaneamente con una **coda** e **multithreading**;
- fornire un **log di funzionamento** per ogni job;
- restare **semplice da ospitare** su un VPS, adattandosi alle risorse;
- **scalare** senza riscritture;
- essere **predisposta** a funzionalità commerciali (auth, quota, pagamenti)
  senza implementarle ora.

Requisiti funzionali principali: upload PDF → scelta pagina/pagine → lingua
origine/destinazione → motore (`google`/`bing`/`llm`) → nome file finale →
output **PDF unito** o **ZIP di pagine singole**; anteprima della pagina per
evitare errori; log live.

---

## 2. Vista d'insieme

```
                          ┌──────────────────────────────────────────────┐
                          │                  Frontend web                │
                          │  upload · parametri · anteprima · log (SSE)  │
                          └───────────────────────┬──────────────────────┘
                                                  │ HTTP /api/v1
      ┌───────────────────────────────────────────┴──────────────────────────┐
      │                             FastAPI (ROLE=api|all)                    │
      │  documents · thumb · jobs · estimate · events(SSE) · system · health  │
      │  ── dipendenze: get_current_actor → authorize → check_quota (no-op)  │
      └───────────────┬───────────────────────────────────┬─────────────────┘
                      │ scrive/legge                      │ legge
                      ▼                                   ▼
        ┌───────────────────────────┐         ┌──────────────────────────────┐
        │  SQLite (fonte di verità) │         │  FileStore (DATA_DIR)        │
        │  jobs · documents · usage │         │  documents/ thumbs/ logs/    │
        │  audit · tables stub      │         │  artifacts/  cache/          │
        └───────────────┬───────────┘         └──────────────┬───────────────┘
                        │ claim atomico (BEGIN IMMEDIATE)     │
                        ▼                                     │
      ┌──────────────────────────────────────────────┐         │
      │           JobQueue (ROLE=worker|all)          │         │
      │  QueueBackend = db | memory                   │         │
      │  N worker thread                              │         │
      └───────────────┬───────────────────────────────┘         │
                      ▼                                          │
      ┌──────────────────────────────────────────────┐         │
      │  pipeline.run_job: blocchi da 100 pagine       │         │
      │  ThreadPoolExecutor(page_concurrency)          │         │
      │  └─ engine.CloneEngine ──► pdf2zh_next (subprocess, .venv2)
      │        split → traduzione → typesetting         │         │
      └───────────────┬────────────────────────────────┘         │
                      └──────────── cache versionata ────────────┘

      CLI (noesis-cloner) ──► stessa pipeline + stessa cache (nessun server)
```

---

## 3. Componenti

| Modulo | Ruolo |
|---|---|
| `app/config.py` | `Settings` da env + autosizing; flag riservati |
| `app/models.py` | Modelli API (pydantic) e record persistenti (dataclass) |
| `app/pages.py` | Parsing specifica pagine (`all`, `7`, `100-103`, `3,5,10-12`) |
| `app/pagelabels.py` | Espansione `/PageLabels` (numerazione stampata) |
| `app/storage.py` | Repository SQLite (WAL) + percorsi filesystem + claim coda |
| `app/migrations.py` | Schema versionato, migrazioni idempotenti |
| `app/engine.py` | Adattatore headless di `pdf2zh_next`: split, cache, lock, cancel, thumb |
| `app/pipeline.py` | **Cuore condiviso**: esecuzione job a blocchi, artefatto, usage |
| `app/queue.py` | `QueueBackend` (db/memory), `JobQueue`, worker |
| `app/worker.py` | Costruzione engine per job + metriche |
| `app/worker_main.py` | Processo worker standalone (multi-processo) |
| `app/resources.py` | Rilevamento CPU/RAM/disco, autosizing, guardie |
| `app/context.py` | Composizione (storage/queue/janitor/runner) e ciclo di vita |
| `app/janitor.py` | Retention di artefatti, log, documenti, thumb |
| `app/auth.py` | Seam identità: `Actor`, `get_current_actor`, `authorize` |
| `app/quota.py` | Seam quota/entitlement + registrazione `usage` |
| `app/security.py` | Sanitizzazione nomi, validazione upload, rate limiter |
| `app/ocr.py` | Seam OCR (rileva pagine senza testo) |
| `app/audit.py` / `app/emailer.py` | Seam audit log / email transazionali |
| `app/logging_setup.py` | Log JSONL per job |
| `app/sse.py` | Streaming SSE con tailing del log |
| `app/estimate.py` | Stima tempo/costo (equazione LLM) |
| `app/metrics.py` | Contatori/gauge Prometheus |
| `app/gtranslate_cli.py` | Catena gratuita per il motore `google` |
| `app/api/v1/` | Route versionate (`documents`, `jobs`, `meta`, `ops`) |
| `app/main.py` | App FastAPI + lifespan |
| `app/templates`, `app/static` | Frontend (Jinja2 + JS vanilla) |
| `app/cli.py` | CLI headless (batch, tqdm) |
| `deploy/` | systemd + nginx di esempio |

---

## 4. Ciclo di vita di un job

```
1. POST /documents        → valida PDF, salva su disco, calcola SHA-256,
                            estrae page_count/etichette/TOC → doc_id
2. (frontend) anteprima   → GET /documents/{id}/thumb?page=N
3. POST /jobs/estimate    → tempo e costo stimati (cache + storico)
4. POST /jobs             → crea Job (stato queued), accoda su DB
5. worker: claim atomico  → stato running; watcher di cancel avviato
6. pipeline.run_job       → per ogni blocco di 100 pagine:
                              ThreadPoolExecutor → engine.translate_page
7. engine.translate_page  → cache hit? ritorna : split → pdf2zh_next → cache
8. artefatto              → PDF unito (merge) o ZIP (pagine singole)
9. stato finale           → done | error | cancelled; usage registrato; log chiuso
10. download              → GET /jobs/{id}/download
```

Stati: `queued → running → (done | error | cancelled)`, più `interrupted`
(job `running` trovato al riavvio del worker).

---

## 5. Modello dati

Tabelle attive:

- **documents**: `doc_id` (uuid), `filename`, `sha256` (chiave cache),
  `page_count`, `path`, `page_labels` (JSON), `toc` (JSON), `owner_id`,
  `size_bytes`, `created`, `updated`.
- **jobs**: parametri (pagine, lingue, motore, `output_name`, `range_mode`),
  `state`, `priority`, progressi, `queue_position`, `error`, `artifact_path`,
  `owner_id`, `created`/`started`/`finished`, `duration_ms`,
  `cancel_requested`.
- **usage**: una riga per job concluso (pagine, caratteri, token, durata) →
  statistiche e base della fatturazione futura.
- **audit**, **emails**.

Tabelle **stub** (vuote, per le evoluzioni): `plans`, `subscriptions`,
`entitlements`, `api_keys`, `teams`, `team_members`, `stripe_events`.

Convenzione trasversale: **la logica usa indici 0-based**, l'utente e l'API
vedono **numeri 1-based**; la conversione avviene in un solo punto.

---

## 6. Decisions records (ADR)

### ADR-001 — Motore come subprocess in venv separato
- **Decisione**: `pdf2zh_next` resta un **eseguibile CLI** invocato come
  subprocess, installato in un venv dedicato (`.venv2`, Python 3.12).
- **Perché**: il motore (BabelDOC, dipendenze pesanti) non convive col venv del
  servizio; l'isolamento dei processi dà anche **robustezza** (un crash del
  motore non abbatte il servizio) e consente il **kill** per il cancel.
- **Alternative**: import diretto delle librerie (conflitti di dipendenze,
  nessun isolamento); container separato (ora disponibile, ADR-017).
- **Conseguenze**: overhead di avvio per pagina; versionamento fissato
  (`pdf2zh_next==2.9.0`).

### ADR-002 — Pipeline unica condivisa server/CLI
- **Decisione**: `pipeline.run_job` è l'unico punto che esegue un job; server e
  CLI lo richiamano con le stesse strutture.
- **Perché**: una sola semantica (cache, log, blocchi, uso), meno duplicazione.
- **Conseguenze**: la pipeline non dipende da FastAPI; testabile con motore finto.

### ADR-003 — SQLite come fonte di verità
- **Decisione**: stato di job/documenti su **SQLite (WAL)**; la coda in memoria
  è solo un acceleratore (o assente con la coda su DB).
- **Perché**: durabilità senza servizi esterni; recupero dopo riavvio; semplicità
  di hosting. L'accesso è serializzato e va bene per carichi modesti/medi.
- **Alternative**: Postgres (futuro, multi-nodo), file JSON (fragili).
- **Conseguenze**: adatto a **un nodo**; per più nodi serve DB condiviso.

### ADR-004 — Coda su database con claim atomico
- **Decisione**: `QUEUE_BACKEND=db` (predefinito). Il worker reclama il job con
  una transazione `BEGIN IMMEDIATE` + `UPDATE ... WHERE state='queued'`.
- **Perché**: consente **1 API + N worker** (anche su più processi) **senza
  Redis**; il claim è atomico e sicuro tra processi.
- **Alternative**: coda in memoria (single-process, `QUEUE_BACKEND=memory`);
  Redis/Celery (futuro per più nodi).
- **Conseguenze**: polling (~0,3 s) invece di notifiche push; accettabile.

### ADR-005 — Ruoli `api` / `worker`
- **Decisione**: `ROLE=all|api|worker`; l'API accoda, i worker eseguono;
  entrypoint separato `python -m app.worker_main`.
- **Perché**: disaccoppia il serving HTTP (leggero, scalabile) dall'esecuzione
  (pesante, CPU/RAM). Abilita lo scaling orizzontale dei worker.
- **Conseguenze**: il **recovery** avviene solo nei worker; il **janitor** in
  `all`/`worker`.

### ADR-006 — Parallelismo a due livelli con limite sui processi motore
- **Decisione**: `ThreadPoolExecutor` per le pagine di un job
  (`PAGE_CONCURRENCY`) **più** un `Semaphore` globale per processo che limita i
  `pdf2zh_next` simultanei (`MAX_ENGINE_PROCS`).
- **Perché**: parallelizza le pagine senza saturare CPU/RAM/rete; il semaforo
  mantiene il numero di subprocess pesanti sotto controllo.
- **Conseguenze**: il limite è **per processo** → con più worker si divide per
  `WORKER_COUNT` (ADR-009).

### ADR-007 — Elaborazione a blocchi da 100 pagine
- **Decisione**: un job può coprire l'intero libro ma le pagine sono processate
  in **blocchi** di `MAX_PAGES_PER_BLOCK` (100), parallele **dentro** il blocco.
- **Perché**: limita picchi di memoria/processi e rende il progresso regolare,
  mantenendo un **unico artefatto** e un unico log.
- **Alternative**: un job per blocco (più output da ricomporre);
  tutto in un colpo (picchi).

### ADR-008 — Cache versionata, atomica e multi-processo
- **Decisione**: chiave = **SHA-256 del contenuto**; percorso cache include
  `cs<schema>-e<versione>[-<hash modello>]`; scritture **tmp + `os.replace`**;
  **lock `flock` inter-processo**.
- **Perché**: la cache condivisa tra server e CLI accelera i job ripetuti e
  sopravvive ai riavvii; il versionamento evita di servire output stantii dopo
  upgrade del motore/cambio modello; l'atomicità evita file corrotti.
- **Conseguenze**: nessuna potatura automatica oggi (vedi §13).

### ADR-009 — Autosizing e guardie
- **Decisione**: `resources.py` rileva CPU/RAM/disco e calcola
  `workers`/`page_concurrency`/`max_engine_procs`; in **container** valgono i
  **limiti dei cgroup** (v2, fallback v1) invece dei valori dell'host letti da
  `/proc`; `ROLE=worker WORKER_COUNT=N` divide le risorse; `AUTOSIZE=false`
  disattiva la deduzione (valori minimi a 1); soglie disco/RAM bloccano nuovi
  job con 503.
- **Perché**: il servizio **si adatta** al VPS (anche dopo resize) e al
  container (`--cpus`/`--memory`) ed evita OOM.
- **Conseguenze**: le env esplicite hanno sempre la precedenza; i valori
  effettivi sono esposti da `GET /api/v1/system`.

### ADR-010 — Anteprima anti-errore (doppia numerazione)
- **Decisione**: miniatura della pagina (o prima/ultima del range) con **numero
  fisico + etichetta stampata** (`/PageLabels`); thumbnail lato server (PyMuPDF,
  cachate) con PDF.js lato client come enhancement opzionale.
- **Perché**: i PDF hanno spesso **due numerazioni** (indice fisico vs numero
  stampato): mostrare entrambe evita errori nella scelta delle pagine.
- **Conseguenze**: la selezione resta per **numero fisico** (quello usato dal
  motore).

### ADR-011 — Log di job in JSONL + SSE
- **Decisione**: ogni job scrive `logs/jobs/<id>.jsonl`; il frontend riceve gli
  eventi via **SSE** facendo il **tail** del file.
- **Perché**: il log è **durabile** (sopravvive a riconnessioni/riavvii) e lo
  streaming non richiede code di eventi in memoria; SSE è semplice e passa dai
  proxy (con buffering off).
- **Conseguenze**: latenza di ~0,5 s; nessun `Last-Event-ID` (replay completo).

### ADR-012 — API versionata `/api/v1`
- **Decisione**: tutte le route sotto `/api/v1` + OpenAPI.
- **Perché**: evolvere i contratti senza rompere i client.

### ADR-013 — Seam commerciali no-op
- **Decisione**: `auth`, `quota`, `ocr`, `audit`, `emailer` e tabelle stub
  esistono ma non alterano il comportamento; `get_current_actor` identifica
  l'anonimo con un cookie.
- **Perché**: attivare auth/pagamenti in futuro **senza migrazioni** né refactor
  di API/pipeline.

### ADR-014 — Stima costo LLM calibrata empiricamente
- **Decisione**: stima tempo dallo **storico** (`usage`); stima costo LLM
  dall'equazione `token_in = (chars/4)·F`, `token_out = token_in·ratio`, con
  `F≈13.3` calibrato su una traduzione reale.
- **Perché**: la stima "naive" sui soli caratteri **sottostimava di ~13×**
  (pdf2zh ripete i prompt per chunk). Vedi §9.

### ADR-015 — Prezzo commerciale esplicito per pagina
- **Decisione**: `COST_CENTS_PER_PAGE_LLM=1` (EUR) vince sull'equazione;
  google/bing gratuiti.
- **Perché**: separa **costo** (tecnico) da **prezzo** (business).

### ADR-016 — Frontend senza build toolchain
- **Decisione**: Jinja2 + JS vanilla (+ CSS), PDF.js opzionale.
- **Perché**: un solo linguaggio nel repo, nessuna dipendenza Node, deploy
  banale. L'API resta il contratto stabile per eventuali SPA future.

### ADR-017 — Distribuzione come immagine Docker multi-arch
- **Decisione**: immagine **linux/amd64 + linux/arm64** pubblicata su **GHCR**
  (`ghcr.io/vigliafg/noesis-pdf-cloner-service`) dalla CI; contiene entrambi i
  venv e gli **asset BabelDOC pre-scaricati** (`babeldoc --warmup`); build e push
  con `docker/build-push-action` (provenance + SBOM).
- **Perché**: distribuzione "out-of-the-box" (`docker run` senza installazioni),
  indipendente dalla macchina; la CI non consuma spazio locale; multi-arch copre
  server x86 e ARM (Docker Desktop su Windows/macOS usa l'immagine Linux).
- **Alternative**: asset scaricati al primo avvio (prima traduzione lenta);
  immagini per-arch senza manifest list.
- **Conseguenze**: immagine grande (~1,5–1,8 GB); gli asset AGPL dei componenti
  (pdf2zh_next, BabelDOC, PyMuPDF) sono incorporati → obblighi di attribuzione e
  offerta del sorgente (`LICENSE`/`NOTICE`); la **traduzione** richiede comunque
  rete in uscita.

---

## 7. Concorrenza e scalabilità

**Limiti attuali (default su 4 core / ~11 GB RAM):**

| Parametro | Valore | Significato |
|---|---|---|
| `workers` | 4 | thread che eseguono job nel processo |
| `page_concurrency` | 3 | pagine in parallelo **per job** |
| `max_engine_procs` | 4 | `pdf2zh_next` simultanei **per processo** |

**Capacità osservata** (cache fredda): ~2–6 pagine/minuto; **istantaneo** per
pagine già in cache. Job concorrenti comodi: 2–4.

**Scaling verticale**: resize del VPS → `AUTOSIZE` ricalcola i limiti.

**Scaling orizzontale (worker)**: `WORKER_COUNT=N` + N unità
`noesis-worker@i`. Ogni processo divide i limiti per N, mantenendo il totale
dei processi motore ≈ capacità della macchina.

**Scaling multi-nodo (futuro)**: `DATA_DIR` condiviso (NFS) oppure backend
**Redis** + **Postgres** + object storage; `QueueBackend` e `Storage` sono già
astratti per questo.

**Cancellazione**: `cancel_requested` su DB + watcher nel worker + kill del
**process group** del subprocess → funziona anche tra processi diversi.

---

## 8. Cache

```
DATA_DIR/
├── documents/<doc_id>.pdf          # upload originali
├── thumbs/<sha256>/page_000156.png # anteprime (cachate)
├── artifacts/<job_id>/...          # output finali (pdf/zip)
├── logs/jobs/<job_id>.jsonl        # log per job
└── cache/
    ├── split/<sha256>/page_000156.pdf
    ├── translated/<sha256>/<engine>/<lang_in>-<lang_out>/
    │        cs3-e1[-<hash_modello>]/page_000156.pdf
    └── engine_events.jsonl          # fallback della catena gratuita
```

Proprietà: chiave sul **contenuto** (stessa traduzione per copie diverse),
**versionata**, **scritta atomicamente**, protetta da **lock inter-processo**.
Il costo di una pagina già in cache è 0 (e la stima lo riflette).

---

## 9. Stima di tempo e costo

**Tempo**: `estimated_seconds = pagine_da_tradurre × ms_per_pagina`, dove
`ms_per_pagina` viene dallo **storico** (`usage`: durata/pagine per motore), con
fallback ai default (`ESTIMATE_MS_PER_PAGE_*`).

**Costo motore LLM** (OpenRouter/Mercury), calibrato su 15 pagine reali:

```
token_in  = (chars_sorgente / 4) × 13.3
token_out = token_in × 1.09
costo_USD = token_in/1e6 × 0.04 + token_out/1e6 × 0.15
# compatto:  costo_USD_pagina ≈ 6.8e-7 × chars_sorgente
```

Misura reale: range 2656–2670 (15 pagine, ~7.924 char/pagina) → **$0.08057**
totali, **~$0.00537/pagina**; la stima naive dava $0.00040 (**~13× in meno**).
Verifica incrociata su un altro range: stimato $0.005441 vs misurato $0.005371
(~1%).

Il **prezzo** mostrato è separato: `COST_CENTS_PER_PAGE_*` (default LLM 1
cent/pagina); le pagine in cache non si pagano.

---

## 10. Sicurezza

- **Validazione upload**: estensione, dimensione (`MAX_UPLOAD_MB=500`), parsing
  PDF, rifiuto file non validi.
- **Sanitizzazione** di `output_name` (no path traversal) e dei nomi file.
- **UUID** non indovinabili per `doc_id`/`job_id`.
- **Rate limit** per attore (finestra scorrevole); **guardie** RAM/disco.
- **XSS**: il frontend usa `textContent` per log e nomi utente.
- **Segreti** solo da env (chiavi LLM non esposte); nessun base-url configurabile
  dall'utente.
- **Seam auth**: `AUTH_MODE=none|proxy|jwt`; in `proxy` si fidano header firmati
  (oauth2-proxy/Keycloak) quando `TRUSTED_PROXY_HEADERS=true`.
- **TLS** delegato al reverse proxy (nginx di esempio incluso).

---

## 11. Osservabilità e operazioni

- **Log applicativo** + **log per job** (JSONL) con eventi per fase/pagina.
- **`/api/v1/metrics`** (Prometheus): job inviati/conclusi/falliti, pagine tradotte,
  lunghezza coda, processi motore attivi.
- **`/api/v1/health`** (stato, motore disponibile, ruolo, coda) e **`/api/v1/system`**
  (risorse, valori effettivi/consigliati).
- **Janitor**: retention (`JOB_RETENTION_HOURS=72`, documenti 24 h, thumb 168 h).
- **Deploy**: `run.sh` (all), `run-api.sh`, `run-worker.sh`; systemd
  `noesis-api.service` + `noesis-worker@.service`; nginx con **SSE senza
  buffering**.

---

## 12. Seam ed evoluzioni future

### 12.1 Autenticazione
- **Con Supabase**: login frontend (supabase-js) → JWT → verifica server via
  **JWKS**; `sub` → `owner_id`.
- **Senza Supabase**: OIDC/OAuth2 (Authlib/`fastapi-users`: Google, GitHub,
  Microsoft, Apple) oppure **reverse proxy** (`AUTH_MODE=proxy`).
- Attivazione prevista: **sostituire `get_current_actor`** e rendere effettivo
  `authorize`; SSE compatibile con **cookie**; linking identity
  (`users(provider, subject)`); upgrade anonimo→account.

### 12.2 Quota e pagamenti (Stripe)
- `check_quota` legge `entitlements`/`plans` e decrementa **atomicamente**;
  `usage` è già registrato per job.
- **Stripe Checkout/Portal** + **webhook** firmati, idempotenti
  (`stripe_events`); piani/crediti; priorità di coda per i paganti.
- Restano da affrontare: IVA/**fatturazione elettronica IT**, rimborsi, SCA/3DS,
  valute, GDPR/DPA.

### 12.3 OCR
- `ocr.page_needs_ocr` rileva le pagine **senza testo**; `FEATURE_OCR` abilita
  un backend (Tesseract/cloud) come step tra `typesetting` e `merge`.

### 12.4 Multi-nodo
- `RedisQueueBackend` dietro `QueueBackend`; `PostgresRepository` dietro
  `Storage`; artefatti su **S3/Supabase Storage**; rate limit condiviso.
- Richiede `DATA_DIR`/storage condiviso e gestione coerenza documenti.

### 12.5 Altro
- **Potatura/quota cache** nel janitor; **streaming token-level** della risposta
  LLM; **progress** più fine; **WebSocket** come alternativa a SSE; **API keys**
  per uso programmatico; **CLI come client remoto** (`--server/--api-key`, già
  abbozzato); **status page** e alerting.

---

## 13. Limiti, rischi e debito tecnico

1. **Licenze/ToS** (rischio massimo per l'uso commerciale): `pdf2zh_next` e
   BabelDOC sono copyleft (AGPL, da verificare); la catena Google usa endpoint
   non ufficiali. Da sciogliere **prima** di vendere il servizio.
2. **Coda su DB adatta a un nodo**: multi-nodo richiede storage condiviso/Redis.
3. **Limite motore per-processo**: il totale va gestito con `WORKER_COUNT`
   (documentato), non è un semaforo globale distribuito.
4. **Cache non potata**: cresce nel tempo (nessuna quota).
5. **Overhead per pagina**: ogni pagina avvia un subprocess (nessun pooling).
6. **Fallback dei motori gratuiti**: possono fallire/essere rate-limited.
7. **OCR assente**: le scansioni senza testo non producono output.
8. **Fairness**: un job lungo può occupare più slot motore.
9. **Recovery**: i job `running` al crash diventano `interrupted` (non ripresi).
10. **PDF.js opzionale**: l'anteprima client richiede la build locale.

---

## 14. Strategia di test

- **Unit/integration** con **motore fittizio** (`FakeEngine`) → nessuna rete,
  nessun `pdf2zh_next`; coprono pipeline (ordine, blocchi, fallimenti parziali),
  coda (priorità, claim, promozione job programmati, recovery), storage,
  sicurezza, autosizing, validazione, API end-to-end (upload/thumb/job/SSE/
  download/estimate/cancel) e CLI.
- **Reali** (manuali, fuori suite): `pdfs/ha22.pdf` con google/LLM, verifica layout,
  misura costi.
- Totale attuale: **70 test**.

---

## 15. Roadmap

**Fase A — prodotto (breve)**
1. Spike **legale/licenze** + benchmark costi per motore. *(Licenze: `LICENSE`
   AGPL-3.0 + `NOTICE` aggiunti con l'immagine Docker, ADR-017.)*
2. Potatura/quota **cache** e cleanup documenti nel janitor.
3. Allineare motore e versioni; hardening operativo (status page, alerting).

**Fase B — commerciale**
4. **Auth** (Supabase o OIDC/proxy) e ownership dei dati.
5. **Piani/quota/uso** + **Stripe** (Checkout, webhook, fatture).
6. **API keys** e CLI client remoto; priorità di coda per piano.

**Fase C — scala/qualità**
7. **OCR** per le scansioni.
8. Multi-nodo: Redis + Postgres + object storage; rate limit distribuito.
9. Cache/pooling avanzato; fairness schedulazione; metriche di costo per job.
