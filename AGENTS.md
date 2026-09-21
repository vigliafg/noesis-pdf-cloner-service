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

## Documentazione
- `README.md` — uso e API.
- `ARCHITETTURA.md` — scelte architetturali (implementate e future), ADR, roadmap.
- `HANDOFF.md` — stato del progetto e TODO.
