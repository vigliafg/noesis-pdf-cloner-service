# Docker

Il servizio è distribuito come **immagine multi-arch** su GitHub Container
Registry:

```
ghcr.io/vigliafg/noesis-pdf-cloner-service
```

Architetture: **linux/amd64** e **linux/arm64**. Gira su Linux, e su Windows e
macOS tramite Docker Desktop (che esegue un container Linux). I **container
Windows nativi non sono supportati**.

L'immagine contiene **tutto** ciò che serve — i due venv (servizio + motore
`pdf2zh_next`) e gli **asset BabelDOC pre-scaricati** — quindi parte subito, senza
installazioni manuali.

## Avvio rapido

```bash
docker run -d --name noesis \
  -p 18080:18080 \
  -v noesis-data:/data \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```

Apri <http://localhost:18080>. I motori **google** e **bing** funzionano subito
(gratuiti, senza chiave). Il motore **llm** richiede la chiave OpenRouter:

```bash
docker run -d --name noesis \
  -p 18080:18080 -v noesis-data:/data \
  -e OPENROUTER_API_KEY="sk-or-..." \
  ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
```

Oppure con **compose** (vedi `docker-compose.yml`):

```bash
docker compose up -d
```

## Configurazione

Tutte le impostazioni sono variabili d'ambiente (le stesse della console, vedi
[`INSTALL.md`](INSTALL.md)). Le più usate:

| Variabile | Default | Note |
|---|---|---|
| `HOST` | `0.0.0.0` | nell'immagine è già `0.0.0.0` |
| `PORT` | `18080` | porta del servizio |
| `DATA_DIR` | `/data` | upload, cache, artefatti, log, `jobs.db` |
| `OPENROUTER_API_KEY` | — | serve solo al motore `llm` |
| `ROLE` | `all` | `all` (API+worker) · `api` · `worker` |
| `WORKERS` | autosize | job in parallelo |
| `PAGE_CONCURRENCY` | autosize | pagine in parallelo per job |
| `MAX_ENGINE_PROCS` | autosize | processi `pdf2zh_next` simultanei |
| `WORKER_COUNT` | `1` | numero di processi worker (per dividere le risorse) |
| `PDF_LLM_MODEL` | `inception/mercury-2.5` | modello LLM |

## Volumi e persistenza

- **`/data`** (volume): dati runtime. Usa un volume nominato (`noesis-data`) o un
  bind mount. Con un **bind mount** la cartella deve essere scrivibile dall'utente
  `noesis` (uid 1000):

  ```bash
  mkdir -p ~/noesis-data && sudo chown -R 1000:1000 ~/noesis-data
  docker run -d -p 18080:18080 -v ~/noesis-data:/data ghcr.io/.../noesis-pdf-cloner-service:latest
  ```

- Gli **asset del motore** (modelli/font BabelDOC) sono già nell'immagine
  (`/home/noesis/.cache/babeldoc`): non si scaricano alla prima traduzione. La
  **traduzione** in sé richiede comunque accesso a Internet in uscita.

## Limiti di risorse e autosizing

All'avvio il servizio calcola da solo `WORKERS`, `PAGE_CONCURRENCY` e
`MAX_ENGINE_PROCS` in base a CPU e RAM. **Dentro un container legge i limiti dei
cgroup** (non le risorse dell'host), quindi:

```bash
docker run -d --cpus 2 --memory 4g ... ghcr.io/.../noesis-pdf-cloner-service:latest
```

calcola i valori per 2 CPU / 4 GB. Se preferisci il controllo esplicito,
imposta le variabili (e `AUTOSIZE=false` per disattivare del tutto l'autosizing):

```bash
-e WORKERS=2 -e PAGE_CONCURRENCY=2 -e MAX_ENGINE_PROCS=2
```

## Scalare (API + worker)

Per più worker paralleli: **1 container `ROLE=api`** + **N container
`ROLE=worker`** che condividono lo **stesso `/data`** (coda su SQLite). Ogni
worker divide le risorse per `WORKER_COUNT`. I worker **non espongono HTTP**
(eseguono `app.worker_main`), quindi non pubblicano porte.

C'è un compose pronto con limiti di risorse: `docker-compose.prod.yml`.

```bash
docker compose -f docker-compose.prod.yml up -d      # 1 API + N worker
```

Oppure a mano:

```bash
docker run -d --name noesis-api -p 18080:18080 -v noesis-data:/data \
  -e ROLE=api -e UVICORN_WORKERS=2 ghcr.io/.../noesis-pdf-cloner-service:latest

for i in 1 2 3 4; do
  docker run -d --name "noesis-w$i" -v noesis-data:/data \
    -e ROLE=worker -e WORKER_COUNT=4 ghcr.io/.../noesis-pdf-cloner-service:latest
done
```

## Diagnostica e CLI nel container

Il repo è in `/app`; la console funziona anche dentro il container:

```bash
docker exec noesis ./noesis status
docker exec noesis ./noesis doctor
docker exec noesis ./noesis logs -n 50
curl -s http://localhost:18080/api/v1/health
curl -s "http://localhost:18080/api/v1/health?deep=1"
```

## Aggiornare

```bash
docker pull ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
docker compose up -d            # ricrea il container con la nuova immagine
```

Il volume `/data` (upload, cache, DB) resta.

## Build locale

Il modo normale per costruire e pubblicare l'immagine è la **CI**
(`.github/workflows/docker.yml`), che non consuma spazio locale. Per un build
manuale:

```bash
docker build -t noesis-pdf-cloner-service:dev .
```

> **Spazio disco**: l'immagine pesa ~1,5–1,8 GB (più la cache di build). Su
> macchine con `/` piccolo conviene reindirizzare Docker su un disco capiente,
> es. `TMPDIR`/cache BuildKit, oppure costruire dentro una VM.

## Pubblicazione (GHCR) e visibilità

La CI pubblica su GHCR a ogni push su `main` (e sui tag `v*`) con i tag
`latest`, `sha-<short>`, `vX.Y.Z`. Perché il `docker pull` funzioni **senza
login**, il package GHCR deve essere **pubblico** (una tantum: pagina del
package → *Package settings* → *Change visibility* → *Public*).

## Note

- **Licenza**: l'immagine incorpora componenti AGPL-3.0 (pdf2zh_next, BabelDOC,
  PyMuPDF). Vedi [`../NOTICE`](../NOTICE) e [`../LICENSE`](../LICENSE).
- **Nessun seam commerciale** attivo (auth/quota/ocr/audit/emailer): come nella
  versione non-Docker.
