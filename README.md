# noesis-pdf-cloner-service

[![tests](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/tests.yml/badge.svg)](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/tests.yml)
[![docker](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/docker.yml/badge.svg)](https://github.com/vigliafg/noesis-pdf-cloner-service/actions/workflows/docker.yml)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-noesis--pdf--cloner--service-2496ED?logo=docker&logoColor=white)](https://github.com/vigliafg/noesis-pdf-cloner-service/pkgs/container/noesis-pdf-cloner-service)
[![license: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

Servizio **server** e **CLI headless** della pipeline di
[noesis-pdf-cloner](https://github.com/vigliafg/noesis-pdf-cloner): apre un PDF,
traduce le pagine scelte **preservandone il layout** e le restituisce in un PDF
unico o in pagine singole (ZIP).

📐 **Documento tecnico delle scelte architetturali (implementate e future):
[`ARCHITETTURA.md`](ARCHITETTURA.md).**

## Che cos'è, in parole semplici

Noesis PDF Cloner prende un PDF e ne **traduce in un'altra lingua le pagine che
scegli**, senza stravolgere l'impaginazione: testo, immagini, tabelle e numeri di
pagina restano al loro posto, cambia solo la lingua. Alla fine ottieni un **PDF
tradotto** da scaricare oppure un **file ZIP** con le pagine tradotte una per una.

Si usa in due modi:

- dal **browser** (interfaccia web): carichi il PDF, scegli le pagine, la lingua
  e il motore di traduzione, premi il pulsante e scarichi il risultato;
- da **riga di comando** (CLI): per lavorare su molti PDF in blocco, anche senza
  aprire il browser.

> Questa è la versione **server + CLI**, pensata per girare su una macchina
> (anche in LAN) e per l'uso da terminale/automazione. La versione **desktop**,
> con interfaccia grafica dedicata, è un progetto separato:
> [noesis-pdf-cloner](https://github.com/vigliafg/noesis-pdf-cloner).

Motore: **[pdf2zh_next v2](https://github.com/PDFMathTranslate/PDFMathTranslate-next)**
(typesetter BabelDOC) con i tre motori di traduzione:

| Motore | Descrizione | Costo |
|---|---|---|
| `google` | catena gratuita (`dict-chrome-ex` → `translate-pa` → `gtx` → Microsoft → LLM) | gratuito |
| `bing` | traduttore Bing built-in di pdf2zh_next | gratuito |
| `llm` | LLM via OpenRouter (`OPENROUTER_API_KEY`) — usa il percorso "OpenAI-compatibile" (`--openai`) di pdf2zh; alias storico `openai` | a consumo |

**In una frase**: carichi un PDF, scegli le pagine, premi "Traduci" e scarichi il
PDF tradotto — con l'impaginazione dell'originale.

## Funzionalità principali (in breve)

### Cosa fa

- **Traduce conservando il layout**: il PDF tradotto mantiene impaginazione,
  immagini, tabelle e note dell'originale; cambia solo la lingua.
- **Selezione pagine flessibile**: una pagina (`7`), un intervallo (`100-103`),
  una lista (`3,5,10-12`) oppure **tutto il libro** (`all`).
- **Due formati di uscita**: un **PDF unico** con le pagine tradotte, oppure uno
  **ZIP** con le pagine tradotte singolarmente.
- **Interfaccia web** con caricamento drag&drop **e CLI** per l'uso in blocco.

### Come ti evita gli errori (punti chiave)

- **Anteprima anti-errore**: prima di tradurre vedi la miniatura della pagina e,
  accanto, **numero fisico + numero stampato** sul documento (`/PageLabels`). Nei
  PDF le due numerazioni spesso non coincidono: così scegli la pagina giusta.
- **Stima prima dell'avvio**: tempo e costo (per il motore `llm`) calcolati
  **prima** di partire, mostrati nel browser.
- **Cache intelligente**: le pagine già tradotte non vengono rifatte; ripetere
  un lavoro è praticamente istantaneo.

### Libri grandi e robustezza

- **Libri interi**: le pagine sono lavorate a **blocchi da 100**, quindi anche un
  volume di migliaia di pagine procede senza "bloccarsi".
- **Coda a priorità**: puoi accodare più lavori e farli eseguire in parallelo.
- **Log completi e avanzamento in tempo reale** nel browser (streaming live).

### Si adatta alla macchina

- **Autosizing**: all'avvio il servizio misura CPU, RAM e disco e regola da solo
  quanto lavoro parallelizzare. In Docker legge i limiti del container.
- **Guardie RAM/disco**: se la macchina è sotto pressione, i nuovi lavori vengono
  temporaneamente rifiutati invece di far crollare il servizio.
- **Scala**: puoi separare "chi riceve i lavori" (API) da "chi li esegue"
  (worker) e aggiungere worker, anche su più macchine.

### Distribuzione

- **Docker multi-arch** (`linux/amd64`, `linux/arm64`) su GHCR, **tutto incluso**
  (motore e asset): si avvia senza installare nulla. Gira su Linux, Windows e
  macOS.
- **CLI headless** con batch multi-PDF e barra di avanzamento, senza server.
- **Cache condivisa e versionata**: server e CLI riusano le stesse traduzioni.
- **Predisposto per il commerciale** (autenticazione, quote, pagamenti): tabelle e
  punti di innesto già presenti, ma **disattivati** di default.

## Requisiti

Non serve saper programmare: si tratta solo di **copiare e incollare** pochi
comandi nel terminale, seguendo i passi indicati.

| Cosa serve | Per quali metodi | Note |
|---|---|---|
| Accesso a **Internet** | tutti | la traduzione contatta servizi online (Google/Bing/OpenRouter) |
| **Docker Desktop** o **Docker Engine** | Metodo C | il più semplice: non installa nulla sul sistema operativo |
| **git** + terminale | Metodi A, B, E | per scaricare il codice e installare |
| **PowerShell** | Metodo B | per l'installazione su Windows nativo |
| Circa **2 GB** di spazio libero | tutti | programma + modelli del motore |

> **Non servono privilegi di amministratore**, tranne se vuoi aprire la porta nel
> firewall per usare il servizio dalla **LAN** (`--open-firewall`).

## Quale installazione scegliere?

| Situazione | Metodo consigliato |
|---|---|
| **Windows/macOS** e vuoi il minimo sforzo | **Metodo C — Docker** |
| **Linux/macOS/WSL** con terminale | **Metodo A — Installer automatico** |
| **Windows** senza Docker | **Metodo B — Windows nativo** |
| Sviluppatore / vuoi controllare ogni pezzo | **Metodo D — Manuale** |
| Macchina **senza Internet** | **Metodo E — Bundle offline** |

Tutti i metodi installano la **stessa applicazione**: cambia solo il modo in cui
arriva sulla macchina. Alla fine il servizio risponde su
<http://127.0.0.1:18080> (o `http://localhost:18080`).

## Installazione passo passo

> La **chiave OpenRouter** è **opzionale**: serve solo al motore `llm`. Senza
> chiave funzionano subito i motori gratuiti `google` e `bing`. La prima
> installazione può richiedere **qualche minuto** (scarica dipendenze e modelli).

### Metodo A — Installer automatico (Linux · macOS · WSL)

1. **Apri il terminale.**

2. **Assicurati che `git` sia installato.** Se non lo è:

   ```bash
   # Ubuntu / Debian / Mint
   sudo apt update && sudo apt install -y git

   # Fedora / RHEL
   sudo dnf install -y git

   # macOS (apre la finestra degli strumenti da sviluppatore)
   xcode-select --install
   ```

3. **Scarica il programma** (copia e incolla, un comando per riga):

   ```bash
   git clone https://github.com/vigliafg/noesis-pdf-cloner-service
   cd noesis-pdf-cloner-service
   ```

4. **Avvia l'installazione:**

   ```bash
   ./install.sh
   ```

   Lo script crea l'ambiente Python, installa il motore di traduzione, scrive la
   configurazione, installa il **servizio con avvio automatico**, chiede la
   chiave OpenRouter (puoi premere `Invio` per saltare) e verifica che tutto
   funzioni.

5. **Attendi il messaggio finale.** A fine installazione vedrai un **report di
   salute**, i link locali e LAN, e l'indicazione che la porta 18080 è
   raggiungibile.

6. **Apri il browser** su <http://127.0.0.1:18080> (di solito si apre da solo).

**Uso in LAN** (altre persone sulla stessa rete): aggiungi la regola firewall
limitata alla sola sottorete locale:

```bash
./install.sh --open-firewall
```

**Se preferisci non installare il servizio di avvio automatico** (solo setup):

```bash
./install.sh --no-service      # poi avvii tu con ./noesis start
```

**Scorciatoia "bootstrap"** (scarica e installa in un colpo solo, nella cartella
`~/noesis-pdf-cloner-service`):

```bash
curl -LsSf https://raw.githubusercontent.com/vigliafg/noesis-pdf-cloner-service/main/bootstrap.sh | bash
```

### Metodo B — Windows nativo (senza Docker)

1. **Installa `git`** da <https://git-scm.com/download/win> (opzioni predefinite).

2. **Apri PowerShell** e scarica il programma:

   ```powershell
   git clone https://github.com/vigliafg/noesis-pdf-cloner-service
   cd noesis-pdf-cloner-service
   ```

3. **Avvia l'installazione:**

   ```powershell
   .\install.ps1
   ```

   > Se compare l'errore *"running scripts is disabled on this system"*, esegui:
   > `powershell -ExecutionPolicy Bypass -File .\install.ps1`

   In alternativa puoi usare `.\noesis.cmd install` (anche da `cmd.exe`).

4. **Attendi il report finale** e **apri il browser** su
   <http://localhost:18080>.

Per l'uso in LAN: `.\install.ps1 -open-firewall` (può richiedere il consenso
amministratore/`UAC`). Per l'avvio automatico **prima del login** (senza accedere
all'utente): `.\noesis.cmd install --mode system` in PowerShell amministratore.

**Alternativa consigliata su Windows: WSL2.** Installa WSL2, apri la distro Linux
e segui il **Metodo A** (`./install.sh`).

**Bootstrap Windows** (scarica e installa in un colpo solo):

```powershell
irm https://raw.githubusercontent.com/vigliafg/noesis-pdf-cloner-service/main/bootstrap.ps1 | iex
```

### Metodo C — Docker (Windows · macOS · Linux)

Il modo più semplice e senza installazioni sul sistema operativo. Serve **Docker
Desktop** (Windows/macOS) oppure **Docker Engine** (Linux), con accesso a
Internet.

1. **Installa Docker Desktop** da <https://www.docker.com/products/docker-desktop/>
   (su Windows abilita il backend **WSL2**).

2. **Apri il terminale** (PowerShell su Windows) e digita:

   ```bash
   docker run -d --name noesis -p 18080:18080 -v noesis-data:/data \
     ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
   ```

3. **Apri il browser** su <http://localhost:18080>.

4. Per abilitare il motore **`llm`** aggiungi la chiave (i motori gratuiti
   `google`/`bing` non la richiedono):

   ```bash
   docker run -d --name noesis -p 18080:18080 -v noesis-data:/data \
     -e OPENROUTER_API_KEY="sk-or-..." \
     ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
   ```

Su Windows PowerShell sostituisci il carattere `\` a fine riga con il backtick
`` ` ``. I dettagli (compose, persistenza, scalabilità, problemi comuni) sono
nella sezione **[Docker in dettaglio](#docker-in-dettaglio)**.

### Metodo D — Manuale, senza servizio (avanzato)

Serve **Python 3.12** e [uv](https://docs.astral.sh/uv/). Utile per sviluppo o
per eseguire il server in primo piano senza installare nulla come servizio.

```bash
./setup_engine.sh     # crea l'ambiente del motore (.venv2) e installa pdf2zh_next
./run.sh              # avvia il server su http://127.0.0.1:18080
```

Con `ROLE=all` (default) il server **deve** girare con un solo processo uvicorn:
in quel processo coda e semafori del motore sono locali e il parallelismo è
interno (thread). Per separare API e worker vedi **Deployment scalabile** più
sotto.

Installando il pacchetto (`pip install -e .`) è disponibile anche il comando
`noesis-cloner`.

### Metodo E — Macchina senza Internet (bundle offline)

1. Su una macchina **già installata**, crea il pacchetto:

   ```bash
   ./noesis bundle      # crea dist/noesis-bundle-<os>-<arch>.tar.gz
   ```

2. Copia il file sulla macchina di destinazione (con il repo clonato) e installa:

   ```bash
   ./noesis install --bundle /percorso/noesis-bundle-<os>-<arch>.tar.gz
   ```

Il bundle contiene i **pacchetti** (servizio + motore) e i **modelli**: non serve
Internet per installare. Serve **un bundle per piattaforma** (Linux x86_64 ≠
macOS arm64 ≠ Windows).

## Primo utilizzo (dal browser)

1. Apri <http://127.0.0.1:18080>.
2. **Trascina il PDF** nella pagina (o selezionalo dal pulsante di caricamento).
3. **Scegli le pagine**: una pagina, un intervallo (`100-103`) o una lista
   (`3,5,10-12`); per un libro intero usa `all`.
4. Controlla l'**anteprima**: vicino alla miniatura vedi sia il **numero fisico**
   sia il **numero stampato** sul documento. Se non coincidono, correggi la
   selezione.
5. Scegli la **lingua di partenza**, la **lingua di destinazione** e il **motore**
   (`google` o `bing` sono gratuiti; `llm` richiede la chiave).
6. Scegli il **formato di uscita**: **PDF unico** oppure **ZIP di pagine
   singole**.
7. Facoltativo: guarda la **stima** di tempo e costo.
8. Premi **Traduci** e segui l'avanzamento in tempo reale; a fine lavoro
   **scarica** il risultato.

## Gestione quotidiana (console `noesis`)

Dopo l'installazione, tutte le operazioni si fanno con un solo comando:

| Comando | Cosa fa |
|---|---|
| `./noesis install` | installa venv, motore, configurazione e servizio |
| `./noesis start` / `stop` / `restart` | avvia / ferma / riavvia in background |
| `./noesis status` | stato del processo e del servizio |
| `./noesis logs -n 100` | mostra le ultime righe di log |
| `./noesis doctor` | diagnostica completa dell'installazione |
| `./noesis open` | apre il frontend nel browser |
| `./noesis update` | aggiorna codice e dipendenze |
| `./noesis uninstall` | disinstalla (scelta interattiva di cosa rimuovere) |

Su Windows usa `.\noesis.cmd` al posto di `./noesis`.

## Aggiornare

```bash
./noesis update      # git pull + aggiornamento dipendenze
```

Con Docker:

```bash
docker pull ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
docker compose up -d            # ricrea con la nuova immagine (i dati restano)
```

## Disinstallare

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

## Docker in dettaglio

### Immagine pronta (multi-piattaforma)

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

**Base — un solo container** (`docker-compose.yml`):

```bash
docker compose up -d          # → http://localhost:18080
```

```yaml
# Noesis PDF Cloner Service — docker compose.
#
#   docker compose up -d      →  http://localhost:18080
#
# La chiave OpenRouter serve solo al motore `llm` (google/bing sono gratuiti).
services:
  noesis:
    image: ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
    container_name: noesis
    ports:
      - "18080:18080"
    volumes:
      - noesis-data:/data
    environment:
      HOST: 0.0.0.0
      PORT: "18080"
      DATA_DIR: /data
      # Chiave per il motore LLM (opzionale).
      # OPENROUTER_API_KEY: "sk-or-..."
      # Limiti espliciti (consigliati): l'autosize legge i limiti del container,
      # ma dichiararli rende il comportamento prevedibile.
      # WORKERS: "2"
      # PAGE_CONCURRENCY: "2"
      # MAX_ENGINE_PROCS: "2"
      # Per più worker: 1 container con ROLE=api + N con ROLE=worker e WORKER_COUNT=N
      # (stesso volume /data).
    restart: unless-stopped
    # Limiti di risorse (docker compose v2 li applica al container).
    # cpus: 2
    # mem_limit: 4g

volumes:
  noesis-data:
```

**Produzione — API + worker** (`docker-compose.prod.yml`):

```bash
docker compose -f docker-compose.prod.yml up -d
```

```yaml
# Noesis PDF Cloner Service — compose di produzione (API + worker).
#
#   docker compose -f docker-compose.prod.yml up -d
#
# Un container API (accoda i job, serve HTTP) e N worker (eseguono i job),
# con lo stesso volume /data (coda SQLite condivisa) e limiti di risorse.
#
# Variabili facoltative (da un file .env accanto a questo file o dall'ambiente):
#   OPENROUTER_API_KEY, API_WORKERS, API_CPUS, API_MEMORY,
#   WORKER_REPLICAS, WORKER_CPUS, WORKER_MEMORY
#
# Nota: WORKER_REPLICAS deve essere il numero TOTALE di worker (le risorse sono
# divise per quel numero all'interno di ogni container).

services:
  api:
    image: ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
    container_name: noesis-api
    ports:
      - "18080:18080"
    volumes:
      - noesis-data:/data
    environment:
      ROLE: api
      HOST: 0.0.0.0
      PORT: "18080"
      DATA_DIR: /data
      UVICORN_WORKERS: "${API_WORKERS:-2}"
      OPENROUTER_API_KEY: "${OPENROUTER_API_KEY:-}"
    restart: unless-stopped
    stop_grace_period: 30s
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:18080/api/v1/health"]
      interval: 30s
      timeout: 5s
      start_period: 30s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: "${API_CPUS:-2}"
          memory: "${API_MEMORY:-2g}"

  worker:
    image: ghcr.io/vigliafg/noesis-pdf-cloner-service:latest
    # Niente container_name: con più repliche il nome deve essere univoco.
    volumes:
      - noesis-data:/data
    environment:
      ROLE: worker
      DATA_DIR: /data
      WORKER_COUNT: "${WORKER_REPLICAS:-2}"
      OPENROUTER_API_KEY: "${OPENROUTER_API_KEY:-}"
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped
    stop_grace_period: 60s
    deploy:
      replicas: ${WORKER_REPLICAS:-2}
      resources:
        limits:
          cpus: "${WORKER_CPUS:-2}"
          memory: "${WORKER_MEMORY:-4g}"

volumes:
  noesis-data:
```

Variabili facoltative del compose di produzione (da `.env` o dall'ambiente):
`OPENROUTER_API_KEY`, `API_WORKERS`, `API_CPUS`, `API_MEMORY`,
`WORKER_REPLICAS`, `WORKER_CPUS`, `WORKER_MEMORY`.

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

## Deployment scalabile (API + worker)

```bash
ROLE=api ./run-api.sh                 # solo API: accoda i job (1..N processi)
WORKER_COUNT=4 ./run-worker.sh        # un processo worker (avviarne N)
```

Con `ROLE=api` l'API non esegue job: i **worker** li reclamano dalla coda
condivisa su SQLite (`DATA_DIR` comune). File systemd/nginx in
[`deploy/`](deploy/README.md).

## CLI headless (senza server)

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
`--log-json`, `-v`, `--list-langs`, `--list-engines`, `--list-pages`,
`--llm-api-key` / `--llm-api-key-file` (BYOK per il motore `llm`; preferisci la
variabile `OPENROUTER_API_KEY`).
Exit code: `0` ok, `1` fallimenti parziali, `2` errore fatale.

Installando il pacchetto (`pip install -e .`) è disponibile anche il comando
`noesis-cloner`.

## Stato del progetto

**Funzionante** (v0.1.0). Verificato end-to-end su un PDF reale (`ha22.pdf`,
4.132 pagine): upload, anteprima, stima, coda, traduzione, download — sia da
**server** sia da **CLI**. Motore `pdf2zh_next 2.9.0` (BabelDOC 0.6.2) in `.venv2`.
Test: **223 passed** (`pytest`, motore fittizio, nessuna rete). Disponibile anche
come **immagine Docker multi-arch**.

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

> La cartella dati dipende dal metodo di installazione: con la console è quella
> standard dell'OS (Linux/WSL `~/.local/share/noesis-pdf-cloner-service`, macOS
> `~/Library/Application Support/noesis-pdf-cloner-service`, Windows
> `%LOCALAPPDATA%\noesis-pdf-cloner-service`); con la CLI/avvio manuale è
> `./data` se non diversamente indicato.

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
| `COST_CENTS_PER_PAGE_GOOGLE` / `_BING` / `_LLM` | `0` / `0` / `0` | prezzo commerciale per pagina in centesimi (default `0` = gratuito: per LLM la stima mostra il costo stimato a carico dell'utente su OpenRouter; alias `_OPENAI`) |
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
| `HELP_URL` | GitHub Pages del repo | URL del pulsante "Guida" in home |
| `TERMS_VERSION` | `1.0` | versione dei Termini (gate + `/meta`) |
| `REQUIRE_TERMS_ACCEPTANCE` | `false` | richiede l'accettazione dei Termini per creare un job (attivare quando esponi) |

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

## Licenza

Il progetto è distribuito con licenza **AGPL-3.0** (vedi [`LICENSE`](LICENSE)).
L'immagine Docker incorpora componenti AGPL-3.0 (pdf2zh_next, BabelDOC, PyMuPDF):
vedi [`NOTICE`](NOTICE) e [`THIRD_PARTY.md`](THIRD_PARTY.md).

Termini aggiuntivi ai sensi della sezione 7 della AGPL:
[`ADDITIONAL_TERMS.md`](ADDITIONAL_TERMS.md). Uso del nome e del marchio:
[`TRADEMARK.md`](TRADEMARK.md). Contributi: [`CONTRIBUTING.md`](CONTRIBUTING.md)
e [`CLA.md`](CLA.md). Vulnerabilità: [`SECURITY.md`](SECURITY.md).

Documenti del **servizio** (in [`legal/`](legal/)): Termini d'uso, Privacy,
Esclusione di garanzia e Uso accettabile, disponibili anche dalle pagine del
servizio (`/terms`, `/privacy`, `/disclaimer`, `/acceptable-use`) e nella guida
pubblicata su GitHub Pages (sezione «Note legali»).

