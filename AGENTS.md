# AGENTS.md — istruzioni per l'agente

Queste istruzioni valgono per il repository `noesis-pdf-cloner-service`.

## Lingua
Rispondere in **italiano**.

## PDF di test — cartella `pdfs/`
- La cartella **`pdfs/`** contiene il **corpus dei PDF usati per i test**
  (es. `pdfs/ha22.pdf`, `pdfs/ce24.pdf`, `pdfs/co23.pdf`, `pdfs/cu25.pdf`,
  `pdfs/pa19.pdf`, `pdfs/pa23.pdf`, `pdfs/su18.pdf`, `pdfs/su19.pdf`).
- Sono documenti reali, di grandi dimensioni (~2–300 MB l'uno) e con copyright:
  **non committarli** (sono esclusi da `.gitignore`). Restano solo in locale.
- Usa questo corpus per test e smoke test reali (traduzione, anteprima, job):
  es. `./run-cli.sh pdfs/ha22.pdf -p 156 --dst it --engine google --output prova`
  oppure `curl -s -F "file=@pdfs/ha22.pdf" http://127.0.0.1:18080/api/v1/documents`.
- Non spostare, rinominare o cancellare i PDF del corpus senza chiedere.
- Se un PDF manca (repository appena clonato), segnalalo: i file non sono
  versionati. Vedi `pdfs/README.md`.

## Comandi utili
- Test: `.venv/bin/python -m pytest -q` (usano un **motore fittizio**, niente rete).
- Motore di clonazione: `./setup_engine.sh` crea `.venv2` con `pdf2zh_next`.
- Server: `./run.sh` (all) · `ROLE=api ./run-api.sh` · `WORKER_COUNT=N ./run-worker.sh`.
- CLI: `./run-cli.sh …` (headless, batch, `tqdm`). `./run-cli.sh --check`.

## Convenzioni tecniche
- **Porta standard del servizio: 18080** (non 8000).
- Due venv: `.venv` (servizio) e `.venv2` (motore `pdf2zh_next`, **Python 3.12**).
- Pipeline unica condivisa da server e CLI (`app/pipeline.py`); non duplicarla.
- **Indici pagina 0-based** nel motore/API interna, **1-based** verso l'utente.
- SQLite è la **fonte di verità**; la coda può essere su DB (`QUEUE_BACKEND=db`).
- I *seam* commerciali (`auth`, `quota`, `ocr`, `audit`, `emailer`) sono no-op:
  non attivarli senza richiesta esplicita.
- Segreti (es. `OPENROUTER_API_KEY`) solo da variabili d'ambiente: non scriverli
  nel codice, nei log o nei commit.

## Modifiche alle funzionalità condivise con `noesis-pdf-cloner`

Questo repository è la **versione server + CLI** della pipeline del progetto
desktop **[`noesis-pdf-cloner`](https://github.com/vigliafg/noesis-pdf-cloner)**
(repo sorgente, tipicamente in `../noesis-pdf-cloner` sulla stessa macchina).

**Regola**: qualunque modifica che riguarda le **funzionalità del programma**
(comportamento del motore/pipeline, traduzione, gestione pagine/cache, output,
catena dei traduttori, ecc.) va **riverberata anche nelle parti di codice
interessate del repository `noesis-pdf-cloner`**, così le due versioni restano
allineate. Vale anche al contrario: una modifica funzionale fatta nel desktop va
riportata qui.

Procedura:
1. Individua la controparte nella tabella qui sotto.
2. Applica la modifica equivalente anche nell'altro repository (stile e
   convenzioni di quel repo: PyQt6/`i18n.py`).
3. Verifica/aggiorna i **test** in entrambi i repository.
4. Riporta esplicitamente cosa è stato allineato e cosa no (e perché).

Non serve riverberare le parti **specifiche del servizio** (API/`app/api`,
frontend web, coda multi-processo, autosizing, ruoli API/worker, deploy):
esistono solo qui e non hanno controparte nel desktop.

### Mappa delle parti condivise

| `noesis-pdf-cloner-service` | `noesis-pdf-cloner` (desktop) | Cosa tenere allineato |
|---|---|---|
| `app/engine.py` | `clone_engine.py` | flag `pdf2zh_next`, split, `doc_key`, schema/percorsi cache, cancel, auto-rilevamento binario |
| `app/gtranslate_cli.py` | `gtranslate_cli.py` | catena gratuita (endpoint, fallback Microsoft/LLM, log eventi) |
| `app/models.py` (`ENGINES`, `LANGUAGES`) | `i18n.py` (`TRANSLATION_ENGINES`, `TRANSLATION_LANGUAGES`) | elenco motori e lingue |
| `app/pages.py` | logica pagine/selezione del desktop | semantica intervalli e convenzione 0-based/1-based |
| `app/pagelabels.py` | gestione etichette/numerazione pagina | doppia numerazione |
| `app/pipeline.py` | flusso export di `main.py` | ordine pagine, blocchi, PDF unito / pagine singole |
| `app/cli.py` | — (equivalente funzionale all'export) | semantica di output e nomi file |

In caso di dubbio su cosa sia "funzionalità" e cosa sia "solo server",
chiedere conferma prima di propagare.

## Convenzione nomi degli output di test
- Cartella **`out/`**, formato `<stem>_p<start>-<end>_<motore>.pdf`, dove
  `<motore>` è **`google`** o **`llm`** (motore LLM/`openai`).
  Es.: `out/ha22_p319-321_google.pdf`, `out/ha22_p319-321_llm.pdf`.
- Il suffisso **`llm`** distingue la traduzione con motore LLM da quella con
  `google`; non usare `_openai`.
- `out/` non è versionata (vedi `.gitignore`).

## Documentazione
- `README.md` — uso e API.
- `ARCHITETTURA.md` — scelte architetturali (implementate e future), ADR, roadmap.
- `HANDOFF.md` — stato del progetto e TODO.
