# Contribuire · Contributing

Grazie per l'interesse! Questo file spiega come contribuire a **Noesis PDF
Cloner Service** (server + CLI). Il repo desktop è
[`noesis-pdf-cloner`](https://github.com/vigliafg/noesis-pdf-cloner).

## Prima di iniziare

- Apri una **issue** per discutere modifiche importanti prima di scrivere molto
  codice.
- Non inserire **segreti** (chiavi, token) in codice, log, issue o commit.
- Non allegare **PDF protetti da copyright** o dati personali/riservati.

## Licenza dei contributi

Contribuendo accetti che il tuo contributo sia distribuito sotto **AGPL-3.0** e
sottoscrivi il **CLA** in [`CLA.md`](CLA.md), necessario per mantenere la
possibilità di gestire la licenza del progetto nel tempo.

## Come contribuire

1. Fai un **fork** e crea un branch descrittivo.
2. Scrivi codice **coerente** con lo stile del repository e allinea le modifiche
   funzionali al repo desktop (vedi `AGENTS.md`).
3. Aggiungi o aggiorna i **test**.
4. Esegui i test **prima** di aprire la pull request:

   ```bash
   .venv/bin/python -m pytest -q
   ```

5. Apri una **pull request** con una descrizione chiara di cosa cambia e perché.

## Convenzioni

- **Lingua**: italiano per commenti e documentazione (le stringhe UI seguono le
  convenzioni del frontend).
- **Motore condiviso**: `app/engine.py` ↔ `clone_engine.py` del desktop; `app/pipeline.py`
  ↔ flusso export del desktop; `app/gtranslate_cli.py` ↔ `gtranslate_cli.py`;
  elenchi motori/lingue `app/models.py` ↔ `i18n.py`. Una modifica va riverberata.
- **Indici pagina**: 0-based nel motore, 1-based verso l'utente.
- **Segreti**: solo da variabile d'ambiente; mai negli argv se evitabile, mai nei
  log.
- **Porta del servizio**: 18080.

## Segnalazioni

- Bug e richieste: **issue** del repository.
- Vulnerabilità: **non** in pubblico — vedi [`SECURITY.md`](SECURITY.md).
