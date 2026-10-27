# TUI per `noesis-pdf-cloner-service`

- **Richiesta**: «fate un piano per trasformare questo servizio in una applicazione TUI. domande primarie: lasciare il -service intatto e fare una copia diversa TUI che replica il workflow del desktop (con i dovuti adattamenti verso un workflow interattivo e semplificato rispetto a quello desktop)? oppure creare una applicazione ibrida service e TUI come estensione interattiva del -service? oppure dare capacità di lancio di una web interface come estensione de -service? quale la soluzione più semplice nell'ottica dell'utente occasionale utilizzatore? infine se l0inyerfsccia tui verrà scelta è meglio farla con rich e textual? presentatemi un piano condiviso»
- **Obiettivo**: dare a un utente occasionale un modo per tradurre un PDF dal terminale, senza server, senza browser e senza imparare flag, riusando la pipeline già esistente.
- **Criteri di successo**:
  1. dopo `./install.sh` bastano **due** gesti: `./noesis` (senza argomenti, su TTY) e un PDF da tradurre;
  2. il percorso completo (file → pagine → lingue → motore → output → file prodotto) si chiude senza mai digitare un flag;
  3. `Esc` annulla un job in corso e le pagine già tradotte restano in cache (secondo avvio rapido);
  4. nessuna regressione: `.venv/bin/python -m pytest -q` verde, server/API/CLI invariati nel comportamento;
  5. la produzione resta **una sola** (`app/pipeline.py`): nessuna copia della pipeline, della cache o delle chiavi motore.
- **Non-obiettivi**: vista affiancata originale/tradotto, traduzione pagina-per-pagina manuale con anteprima grafica, editing del testo tradotto, notifiche/suoni, temi, i18n della TUI, modalità remota via API (`--server`/`--api-key`, seam già esistente in `app/cli.py:121-122`), OCR, TUI nell'immagine Docker, "ritraduci ignorando la cache".
- **Assunzioni** (da confermare in fase di OK):
  - target primario Linux/macOS/WSL; Windows nativo *best effort* (Textual gira in Windows Terminal, non è gate di rilascio);
  - utente occasionale = persona sulla propria macchina, che non vuole imparare i flag e che accetta di lasciare il terminale aperto durante la traduzione;
  - TUI in italiano, stringhe centralizzate in un solo modulo (i18n futura senza toccare le schermate);
  - nessun cambiamento di comportamento di server, API e CLI.

---

## 1. Risposta alle domande primarie

### A, B o C?

| | cosa costa | cosa dà | verdetto |
|---|---|---|---|
| **A. Copia/fork TUI separato che replica il desktop** | un secondo repo, una seconda cache, una seconda configurazione, doppia manutenzione; duplica esattamente ciò che il repo impone unico (`app/pipeline.py:1-7`, `AGENTS.md` §"Pipeline unica condivisa da server e CLI; non duplicarla") | isolamento totale dal service | **scartata** |
| **B. TUI ibrida nello stesso repo, in-process, come nuovo client della pipeline** | un modulo nuovo, una dipendenza opzionale, un comando console | un solo install, una sola cache (`EngineCache`), un solo `noesis.env`, nessuna porta, funziona in SSH; stesso schema già usato dalla CLI (`app/cli.py:272-280` chiama `run_job`) | **scelta** |
| **C. Launcher della web interface** | **nulla**: esiste già (`tools/noesis.py:1618` `start`, `tools/noesis.py:1815` `open`, app in `app/main.py:80`) | l'esperienza migliore: anteprime vere, drag & drop, wizard web (`app/templates/index.html:36-139`) | **non è un'alternativa**: è la superficie "ricca" che la TUI offre a un tasto |

**Perché B è la più semplice per l'utente occasionale.** Le tre superfici condividono la stessa `Settings` letta da `DATA_DIR` + `noesis.env` (`app/config.py:54-69`, iniettata dalla console in `tools/noesis.py:538-551`): stessa cache, stessa cronologia, stessa chiave. La TUI non aggiunge un secondo modello di configurazione né un demone da avviare: `./noesis` apre una finestra di testo, `./noesis open` apre il browser. Chi ha bisogno delle anteprime grafiche non perde nulla; chi lavora in SSH non ha alternative.

**Cosa B non risolve (e va detto)**: la TUI non mostra la pagina. Il desktop è *preview-first* (pagina a sinistra, clone a destra, `▶ Traduci` per pagina); il terminale non può farlo. La TUI è quindi **batch-first**: selezione → traduzione → file. L'anti-errore del desktop (doppia numerazione fisica/stampata, ADR-010 in `ARCHITETTURA.md:250`) resta, ma su **testo**: etichette `/PageLabels` (`CloneEngine.page_labels`, `app/engine.py:479`) e prime righe della prima/ultima pagina selezionata.

### Rich o Textual?

**Textual** (che porta con sé Rich). Rich da solo è un renderer: con Rich bisognerebbe scrivere a mano loop eventi, focus, form, worker in background e cambio schermata. Textual 8.2.8 (PyPI, `requires-python >=3.9,<4.0`, dipende da `rich>=14.2`) copre tutto e offre `run_test()` per test headless in CI. Compatibile con `requires-python = ">=3.10"` del repo (`pyproject.toml:10`).

Regola: la logica (selezione pagine, nomi, riepiloghi, diagnostica) **non importa Textual**; solo le schermate lo fanno. Così i test veloci restano veloci e la UI è sostituibile.

---

## 2. Vincoli dal repository

- `AGENTS.md`: pipeline unica, non duplicarla; porta 18080; due venv (`.venv` servizio, `.venv2` motore); indici pagina **0-based** interni e **1-based** verso l'utente; SQLite fonte di verità; segreti solo da ambiente; modifiche funzionali al motore da riverberare su `../noesis-pdf-cloner`.
- `AGENTS.md` §parità: la TUI è superficie **service-specifica** (console/CLI), quindi **nessun riverbero** sul desktop. Il piano non tocca `app/engine.py`, `app/gtranslate_cli.py`, `app/models.py` (ENGINES/LANGUAGES): i test di parità (`tests/test_desktop_parity.py`) restano validi.
- `pyproject.toml:29`: `packages = ["app", "app.api", "app.api.v1"]` — va esteso, altrimenti la TUI non finisce nel wheel.
- `Dockerfile:51-54`: il container installa solo `requirements.txt`. La TUI non entra nell'immagine.
- `AGENTS.md` §comandi: i test girano con `.venv/bin/python -m pytest -q` e usano un motore fittizio (niente rete).

## 3. Stato attuale (punti di innesto)

Esiste già quasi tutto ciò che serve; la TUI è un **client** di questi pezzi:

| pezzo | dove | cosa offre |
|---|---|---|
| esecuzione job | `app/pipeline.py:49` `run_job(...)`, cancel a `:57`, callback `on_page_done` a `:194` | traduzione a blocchi, artefatto finale in ordine di pagina (`:202`) |
| uso in-process | `app/cli.py:217-298` `_process_one` → `run_job` a `:272`, copia output a `:283-288` | schema esatto da replicare per la TUI |
| motore | `app/engine.py:371` `doc_key`, `:472` `page_count`, `:479` `page_labels`, `:819` `translate_page`, `:750-792` subprocess con cancel entro 1 s (`:778-780`) | traduzione pagina, cache su disco, kill su cancel |
| pagine | `app/pages.py:78` `parse_pages`, `:105` `format_pages_label` | parsing e etichette compatte |
| nomi file | `app/security.py:16` `sanitize_stem` | nome output sicuro |
| stato | `app/storage.py:133` `create_job`, `:163` `list_jobs(owner_id=…)`, `:217` `claim_next_job`, `:448` `artifact_dir` | SQLite WAL, lock interno, `check_same_thread=False` (`:59-70`) |
| modelli | `app/models.py:20` `ENGINES`, `:35` `LANGUAGES`, `:54` `JobState`, `:214` `DocumentRecord`, `:229` `JobRecord` | dati già pronti |
| stima | `app/estimate.py:77` `estimate_job` | pagine in cache, tempo, costo (meglio sforzo) |
| diagnostica | `app/diagnostics.py:512` `run_all`, `:542` `build_context`, `:532` `health_status`; formattazione in `app/cli.py:301-326` | controlli runtime |
| log job | `app/logging_setup.py:28` `JobLogger.event(...)` | eventi strutturati già emessi da `run_job` |
| pulizia | `app/janitor.py:48` `Janitor.cleanup()` | cleanup una tantum |
| recovery | `app/jobqueue.py:200` `_recover` (running → interrupted) | pattern da riusare, per owner `tui` |
| console | `tools/noesis.py:2083` `cmd_cli` (execvpe + `build_env`), `:2203` `_HANDLERS`, `:2237-2244` help senza argomenti; installer `:1443-1475`, wheelhouse `:1373-1384` | dove si aggancia il comando `tui` |
| test | `tests/helpers.py:12` `make_pdf`, `:35` `FakeEngine`, `:56` `FailingEngine`, `:73` `SlowFirstEngine` | motore fittizio già pronto |

## 4. Approccio proposto

Un pacchetto `app/tui/` **piatto** (niente sottopacchetti: una sola voce in `packages`), entry point `python -m app.tui`, avviato da `tools/noesis.py` con lo stesso `build_env(data_dir)` della CLI, così `DATA_DIR` e `noesis.env` sono quelli del server.

```
app/tui/__init__.py
app/tui/__main__.py   # main(): Settings.from_env(), Storage, guardie, NoesisTUI().run()
app/tui/jobs.py       # puro, senza Textual: selezione, nomi, anteprima testuale, riepilogo, righe diagnostica
app/tui/runner.py     # thread che esegue run_job, eventi → callback, cancel(), stato terminale garantito
app/tui/screens.py    # Home, Wizard (5 passi), Esecuzione, modale Diagnostica — unico file che importa Textual
app/tui/app.py        # App: CSS, bindings, composizione schermate
```

Schermate e comportamento:

1. **Home** — tabella dei soli job `owner_id="tui"`, colonne: quando, file, pagine, motore, stato, output. Niente ricerca, filtri, miniature o formattazioni. Azioni: `n` nuovo lavoro, `enter` dettaglio, `o` apri cartella dell'output, `d` diagnostica, `w` interfaccia web, `q` esci.
2. **Wizard 5 passi** — file → pagine → lingue → motore → output, come il wizard web (`app/templates/index.html:36-139`) e l'export desktop. Passo "pagine": campo libero con le stesse regole di `parse_pages` (`all`, `7`, `100-103`, `3,5,10-12`), conteggio, etichette fisiche/stampate e **anteprima testuale** (prime righe della prima e dell'ultima pagina, estratte con PyMuPDF, già dipendenza). Passo "output": nome proposto `<stem>_<dst>` (come `app/cli.py:236`), cartella (default: cwd), `merged` | `single`; in coda, una riga di stima best-effort via `estimate_job` (se fallisce, si nasconde).
3. **Esecuzione** — barra, stato per pagina (1-based), log dal `JobLogger`, `Esc` = annulla (`threading.Event`). Al termine: percorso del file, `o` apri cartella, `n` nuovo lavoro. Annullamento: effetto entro pochi secondi (`app/engine.py:778-780` controlla ogni secondo; `app/pipeline.py:107` scarta le pagine non ancora avviate).
4. **Diagnostica** — modale con le righe di `run_all(build_context(settings))`; niente file dedicato, riusa la formattazione di `app/cli.py:301-326`.

**Guardie** (dettaglio in §7): niente co-esecuzione con un server attivo, niente job se `REQUIRE_TERMS_ACCEPTANCE` è attivo, recupero dei job `tui` rimasti `running`, una pulizia `Janitor.cleanup()` all'avvio.

---

## 5. Passi

1. **Dipendenze e packaging** — file: `requirements-tui.txt`, `pyproject.toml`, `app/tui/__init__.py`
   - `requirements-tui.txt` con `textual>=8,<9`; extra `tui` in `[project.optional-dependencies]` (`pyproject.toml:25`); `app.tui` in `packages` (`pyproject.toml:29`).
   - Verifica: `uv pip install --python .venv/bin/python -r requirements-tui.txt` e `.venv/bin/python -c "import app.tui, textual; print(textual.__version__)"`. Rischio: S.

2. **Factory condivisa documento + job + engine** — file: `app/job_factory.py` (nuovo), `app/cli.py`
   - Estrarre dalla CLI ciò che la TUI duplicherebbe: `build_engine(settings, api_key=None)` (oggi `app/cli.py:176-197`, 17 parametri) e `create_document_and_job(...)` (oggi `app/cli.py:200-214` + `:236-250`, incluso il controllo `max_pages_total` a `:233`). `app/cli.py` passa alla factory **senza cambiare comportamento**; `app/worker.py:51-74` e `app/estimate.py:86-95` restano come sono (nessun churn non richiesto).
   - Verifica: `tests/test_cli.py` (end-to-end merged e ZIP), `tests/test_pipeline.py`, `tests/test_queue.py`. Rischio: S/M.

3. **Logica headless della TUI** — file: `app/tui/jobs.py`, `tests/test_tui_jobs.py`
   - Funzioni pure: `preview_selection(pdf, pages)` (prima/ultima pagina, etichetta, snippet di testo; pagina senza livello testuale → stringa vuota, non errore), `suggest_output(...)`, `summary_lines(...)`, `doctor_rows(settings)`, `copy_artifact(result, out_dir)`.
   - Test: PDF generato con `make_pdf` (`tests/helpers.py:12`), pagine senza testo, specifica non valida, nome con caratteri strani, `max_pages_total`. Rischio: S.

4. **Runner dei job** — file: `app/tui/runner.py`, `tests/test_tui_runner.py`
   - `JobRunner`-lite: thread, `run_job(storage, engine, job, settings, logger, on_page_done, cancel_event)` (`app/pipeline.py:49`), eventi inoltrati a callback, `cancel()`, `try/except` che garantisce **sempre** uno stato terminale (`error` + `finished`) se `run_job` solleva prima di aggiornare il job (es. documento mancante, `app/pipeline.py:64-75`).
   - All'avvio: job `owner_id="tui"` in `running` → `interrupted` con `finished` e `duration_ms` valorizzati (schema `app/jobqueue.py:200-208`, così `storage.old_jobs` a `:415` li può ripulire).
   - Test: `FakeEngine` (successo), `FailingEngine` (pagina fallita → job `done` con `pages_failed>0`), engine fittizio che onora `cancel_event` (annullamento), eccezione pre-pipeline → `error` + `finished`. Rischio: M.

5. **App Textual: shell, Home, Diagnostica** — file: `app/tui/app.py`, `app/tui/screens.py`, `tests/test_tui_app.py`
   - Bindings, tema, refresh della Home, modale diagnostica, guardia non-TTY (messaggio + exit code 2). Test headless con `asyncio.run(...)` + `run_test()` (nessun `pytest-asyncio` aggiuntivo). Rischio: M.

6. **Wizard** — file: `app/tui/screens.py`
   - 5 passi, validazioni riusate (`parse_pages`, `sanitize_stem`), campo chiave OpenRouter mascherato se motore `llm` e chiave assente (stesso controllo di `app/cli.py:388-394`), stima best-effort. Test: funzioni di validazione (puri) + pilot test che compila i 5 passi e crea il job. Rischio: M.

7. **Schermata di esecuzione** — file: `app/tui/screens.py`
   - Barra, griglia pagine, log, annulla; passaggio a fine job. Test: pilot con `FakeEngine` su 2-3 pagine; cancel con motore lento. Rischio: M.

8. **Integrazione console e installazione** — file: `tools/noesis.py`, `tests/test_console.py`
   - `cmd_tui` sul modello di `cmd_cli` (`tools/noesis.py:2083-2094`): `execvpe(venv_python, ["-m", "app.tui"], build_env(data_dir))`; comando `tui` in `_HANDLERS` (`:2203`) e in `build_parser` (`:2118`).
   - Nessun argomento: TUI **solo** se `stdin` e `stdout` sono TTY, altrimenti help come oggi (`:2243`) — niente regressione per script e CI.
   - `ensure_service_venv` (`:667-671`) installa anche `requirements-tui.txt`; `--no-tui` su `install`/`update`; `download_wheels` (`:1373-1384`) include il nuovo manifest, altrimenti i bundle offline si rompono.
   - Test: handler con `DRY_RUN`, costruzione env (`build_env`), ramo TTY/non-TTY, bundle manifest. Rischio: M.

9. **Documentazione e chiusura** — file: `README.md`, `docs/INSTALL.md`, `HANDOFF.md`, `ARCHITETTURA.md`
   - Sezione "TUI" nel README (comandi, limiti, differenze dal web/desktop), nota in INSTALL, voce in HANDOFF, riga in roadmap. Poi `.venv/bin/python -m pytest -q`.

**Totale: M/L** (9 passi, di cui uno L: la UI).

## 6. Alternative considerate (e perché scartate)

- **Wizard a prompt dentro `app/cli.py`** (`--interactive`, `input()` + tqdm): è la variante più corta in assoluto (~100-150 righe, zero dipendenze, `cmd_cli` già passthrough, `tools/noesis.py:2083-2094`). Scartata come **v1** perché la richiesta è una *applicazione TUI* (schermate, stato, annullamento visibile), non una CLI che fa domande. Resta la scorciatoia per chi non vuole Textual: la CLI attuale fa già tutto con i flag.
- **Import diretto dei privati della CLI** (`from .cli import _make_engine`) invece della factory: zero file toccati, ma accoppia la TUI agli internals di un modulo argparse/tqdm e rende il drift silenzioso. Preferita la factory (passo 2) limitata a CLI + TUI.
- **`--force` / "ritraduci ignorando la cache"** nella TUI: la CLI cancella i file di cache **fuori** dal lock di traduzione (`app/cli.py:252-257` vs `app/engine.py:845-852`); in presenza di un altro processo è una corsa. Fuori scope v1.
- **Modo "attach al server"** (TUI come client HTTP dell'API, riusando il seam `--server` di `app/cli.py:121-122`): utile, ma è un secondo modello di esecuzione (auth, polling, SSE) e non serve all'utente occasionale. Seam futuro.
- **`noesis open --start`** (avvio del server da un comando): rimandato; oggi `start` + `open` sono due comandi e vanno bene.

## 7. Riconciliazione del Concilio

| # | rilievo | chi | severità | decisione | motivo |
|---|---------|-----|----------|-----------|--------|
| 1 | `Esc` non annulla "subito": chi attende uno slot motore non vede il cancel fino all'acquisizione | Luna | MAJOR | **respinto** | Il kill avviene entro 1 s (`app/engine.py:778-780`); le pagine non ancora avviate escono subito (`app/pipeline.py:107`); l'attesa di 900 s si verificherebbe solo se nessuno slot si liberasse — ma i processi in corso vengono uccisi dal cancel stesso. Il piano **non promette** "immediato": promette "entro pochi secondi" e lo verifica con un test |
| 2 | La chiusura del terminale può lasciare vivo il subprocess del motore (`start_new_session=True`) | Luna | MAJOR | **accettato (documentato + mitigazione)** | `app/engine.py:771` isola il figlio dai segnali del terminale. Mitigazione: all'uscita la TUI imposta il cancel e attende il drain con timeout; l'orfano al massimo completa una pagina e scrive in cache atomica. Limite scritto nel README |
| 3 | Server attivo e TUI possono co-eseguire sullo stesso `DATA_DIR`; `_recover` marca `running` → `interrupted` anche i job TUI | Luna | MAJOR | **accettato** | La conferma utente non basta: la TUI **rifiuta** di creare job se `/api/v1/health` risponde (ricontrollo prima di ogni avvio), e propone la web UI. Nessuna modifica al server |
| 4 | `--force` cancella cache condivisa fuori dal lock | Luna | MAJOR | **accettato** | Voce rimossa dalla v1 (vedi §6) |
| 5 | Job recuperati `interrupted` senza `finished` non rientrano nella retention; nessun janitor nel processo TUI | Luna | MAJOR | **accettato** | Il recovery del passo 4 scrive `finished`/`duration_ms`; `Janitor.cleanup()` eseguito una volta all'avvio (`app/janitor.py:48`), best-effort |
| 6 | Un'eccezione prima dell'aggiornamento di stato lascia il job `running` | Luna | MAJOR | **accettato** | Passo 4: `except` nel runner con stato `error` + `finished` |
| 7 | La TUI bypassa `REQUIRE_TERMS_ACCEPTANCE` | Luna | MAJOR | **accettato** | Se il gate è attivo (`app/config.py:205`, controllo in `app/api/v1/jobs.py:57-62`) la TUI non crea job e rimanda alla web UI: nessuno stato nuovo nel DB |
| 8 | `./noesis` senza argomenti → TUI cambia il default della console | Luna | MAJOR | **accettato con mitigazione** | TUI solo con `stdin` **e** `stdout` TTY; in pipe/CI resta l'help e il codice 0. Test dedicato ai due rami |
| 9 | L'extra Textual non entra nei percorsi di installazione e bundle esistenti | Luna | MINOR | **accettato** | Passo 8: `ensure_service_venv` + `--no-tui` + `download_wheels` |
| 10 | "B è più semplice per l'occasionale" non è dimostrato | Luna | MINOR | **accettato** | Aggiunto il criterio di successo n. 1 (due gesti) e una prova d'uso manuale in §10 |
| 11 | La citazione del frontend riguarda miniature, non estrazione testo | Luna | MINOR | **accettato** | L'anteprima testuale è comportamento **nuovo** (PyMuPDF) ed è testata anche su pagine senza testo |
| 12 | Citazioni `file:riga` imprecise (`storage.py:163`, `:217`, `noesis.py:2243`) | Luna | MINOR | **accettato** | Corrette in §3 |
| 13 | I passi 2-4 duplicano funzioni già in `app/cli.py`; `build_engine` tocca 3 file per 20 righe | GLM | BLOCKER | **accettato in parte** | Estratta la factory (passo 2) ma **solo** per CLI+TUI; `worker.py`/`estimate.py` non si toccano. `_process_one` non è riusabile (crea barre tqdm e stampa, `app/cli.py:259-266`) |
| 14 | Alternativa più corta non valutata: wizard a prompt in `app/cli.py` | GLM | BLOCKER | **respinto come v1, citato come alternativa** | La richiesta è una TUI, non una CLI interrogativa; il costo maggiore è accettato dall'utente che chiede Textual. Documentato in §6 |
| 15 | Home con storico job = duplica `noesis status` e la vista web | GLM | MAJOR | **accettato in parte** | Home mantenuta ma ridotta a tabella essenziale (nessuna ricerca/filtro/miniatura, annullamento solo nella schermata di esecuzione): è il punto d'ingresso di una *app*, e serve a riaprire l'output |
| 16 | Passo 8 con scope creep (`--no-tui`, wheel nel bundle, `open --start`) | GLM | MAJOR | **accettato in parte** | `open --start` rimosso; `--no-tui` e wheelhouse restano perché la dipendenza è installata di default (altrimenti i bundle offline si rompono) |
| 17 | Schermata Diagnostica dedicata duplica `_run_doctor` | GLM | MAJOR | **accettato** | Nessun file dedicato: modale che rende le righe di `run_all` |
| 18 | Anteprima pagine non essenziale | GLM | MINOR | **respinto** | È l'unico sostituto dell'anteprima grafica e l'anti-errore del progetto (ADR-010); resta semplice (prime righe, prima/ultima pagina) |
| 19 | `estimate_job` non richiesto dai criteri | GLM | MINOR | **respinto in parte** | Tenuta come **una riga** best-effort nello step output: su un libro da 300 pagine è l'informazione che evita un avvio sbagliato. Se la chiamata fallisce, sparisce |
| 20 | Job creato in `running`: deviazione dal flusso CLI | GLM | MINOR | **accettato** | Documentato nel codice e in questo piano; serve a non farlo reclamare da `claim_next_job` (`app/storage.py:217`) |
| 21 | Textual solo in fase 2 | GLM | MINOR | **respinto** | Contraddice la richiesta esplicita ("è meglio farla con rich e textual?") |

Nessun rilievo irrisolto. Un solo dubbio strutturale (Home sì/no, `estimate` sì/no) è stato deciso, non mediato: Home minima + stima su una riga.

## 8. Verdetto dei critici

- **Luna**: `APPROVE_WITH_CHANGES` — «l'architettura è praticabile, ma annullamento, concorrenza, recovery e compatibilità della console richiedono correzioni prima di approvare la bozza». Blocker: nessuno; 8 major elencati in tabella, tutti chiusi.
- **GLM**: `APPROVE_WITH_CHANGES` — «la raccomandazione B è giusta, ma la v1 integrale è più grande del problema: la modalità interattiva nella CLI soddisfa i criteri di successo con ~1/6 del lavoro e zero dipendenze; Textual diventa fase 2». Blocker: 2, chiusi rispettivamente con la factory e con l'alternativa documentata.

## 9. Rischi e mitigazioni

| rischio | probabilità | impatto | mitigazione |
|---|---|---|---|
| Co-esecuzione con un server attivo sulla stessa `DATA_DIR` | media (utenti che hanno già installato il servizio) | stato job incoerente, CPU satura | rifiuto di avviare job se `/api/v1/health` risponde, ricontrollato prima di ogni avvio |
| `Esc` percepito come lento | media | UX | messaggio "annullamento in corso…", test con motore lento |
| Terminale chiuso durante il job → motore orfano per una pagina | media | CPU per pochi secondi | cancel all'uscita + drain con timeout; limite documentato |
| Textual su terminali poveri (no unicode/truecolor) | bassa | resa scadente | fallback `--no-color`/ASCII non in v1; documentato |
| Crescita di `data/` senza server | media | disco | `Janitor.cleanup()` all'avvio + retention già configurata (`app/config.py:132-136`) |
| Bundle offline senza i wheel Textual | media | install offline rotta | `download_wheels` esteso (passo 8) |
| Rifattorizzazione della factory rompe la CLI | bassa | regressione su script | test CLI end-to-end già esistenti (`tests/test_cli.py`), nessun cambio di semantica |

## 10. Test e verifica

```bash
# dipendenze e import
uv pip install --python .venv/bin/python -r requirements-tui.txt
.venv/bin/python -c "import app.tui, textual"

# unit + integrazione (motore fittizio, niente rete)
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_tui_jobs.py tests/test_tui_runner.py tests/test_tui_app.py
.venv/bin/python -m pytest -q tests/test_cli.py tests/test_console.py
.venv/bin/python -m pytest -q tests/test_desktop_parity.py

# smoke manuale (PDF reali del corpus, non versionati)
./noesis tui                 # Home → nuovo lavoro → pdfs/ha22.pdf → 319-321 → it → google → out/
./noesis tui                 # seconda esecuzione: le pagine sono in cache, il job è quasi istantaneo
```

Casi limite coperti dai test: pagine fuori intervallo e specifica vuota; PDF senza livello testuale (anteprima vuota, non crash); annullamento durante la traduzione; eccezione prima del job; recupero di un job `tui` rimasto `running`; console senza TTY; `REQUIRE_TERMS_ACCEPTANCE=1`; server attivo.

Prova d'uso (criterio n. 1): su una macchina pulita, `./install.sh` → `./noesis` → tre tasti → file in `out/`. Se servono più di due comandi, il criterio non è soddisfatto.

## 11. Criteri di accettazione

1. `./noesis` su TTY apre la TUI; in pipe stampa l'help ed esce 0.
2. Un PDF del corpus si traduce dall'inizio alla fine senza digitare flag, con output in `out/` e nome `<stem>_<pagine>_<motore>.pdf`.
3. La seconda esecuzione sulle stesse pagine è quasi istantanea (cache riusata).
4. `Esc` chiude il job come `cancelled`, la TUI resta usabile e le pagine completate restano in cache.
5. Con il server attivo, la TUI non avvia job e lo dice.
6. `--no-tui` installa il servizio senza la dipendenza; il bundle offline include i wheel Textual.
7. `pytest -q` verde; `tests/test_desktop_parity.py` invariato.

## 12. Domande aperte / condizioni per l'assenso

1. **Windows nativo** è un requisito di rilascio o *best effort*? (cambia il peso dei test console e dei percorsi).
2. La dipendenza Textual va installata **di default** dall'installer (scelta del piano, per l'utente occasionale) o solo su richiesta (`--with-tui`)?
3. La TUI deve restare **solo locale** (nessun `--server`), o volete già il seam "client dell'API" in questa fase?
4. La Home con lo storico dei job TUI serve, o preferite un unico flusso "nuovo lavoro" senza cronologia? (il piano la tiene, minima).

---

## 13. Esito dell'implementazione (2026-10-27)

Implementati tutti i 9 passi. Test: **363 passed** (erano 334; +29 nuovi:
`tests/test_tui_jobs.py`, `tests/test_tui_runner.py`, `tests/test_tui_app.py`,
più i test console su `tui`, `--no-tui` e manifest).

File nuovi: `app/job_factory.py`, `app/tui/{__init__,__main__,app,screens,jobs,runner}.py`,
`requirements-tui.txt`.

Scostamenti rispetto al piano, con motivo:

1. **Niente `estimate_job` nel wizard.** La stima richiede la chiave del
   documento (`sha256` = lettura integrale del PDF) *prima* che il job esista:
   un costo sul percorso critico per un'informazione secondaria. Al suo posto,
   alla partenza, la schermata di esecuzione mostra **quante pagine sono già in
   cache** (`engine.cached_pages`), che è il dato davvero utile (le pagine in
   cache sono istantanee). Il resto della stima resta nella web UI.
2. **Annullamento**: nessuna modifica a `app/engine.py` (era un rilievo di
   Luna). Il test `test_runner_cancel` verifica l'annullamento di una
   traduzione **in corso**; il messaggio "annullamento in corso…" resta visibile
   e non viene sovrascritto dal tick di avanzamento.
3. **Recovery**: i job `tui` rimasti `running` diventano `interrupted` con
   `finished` e `duration_ms` (retention) e il janitor gira una volta all'avvio.
4. **Guardie**: rifiuto se il server risponde (ricontrollato all'avvio del job,
   non solo all'apertura), rifiuto se `REQUIRE_TERMS_ACCEPTANCE` è attivo,
   nessuna opzione "ignora la cache".
5. **Console**: `--no-tui` su `install`/`update`, wheel TUI nel bundle,
   `./noesis` senza argomenti apre la TUI **solo** su TTY; in pipe resta l'help.
6. **Home minima** come deciso: tabella essenziale, nessun filtro; `Esc`/`q`
   non abbandonano un job in corso (prima si annulla).

### Aggiornamento 0.2.1 — allineamento alle altre TUI della famiglia

Dopo il rilascio 0.2.0 la TUI è stata portata alla pari con le due TUI già
esistenti (`noesis-pdf-reader-lite-engine -gui`, `noesis-ebook-translator-engine -gui`):

- **selettore di file** (`FilePicker` con `DirectoryTree` filtrato su `.pdf`)
  accanto al campo digitabile;
- **tema** `auto|dark|light` (`--theme`, tasto `t`; `ansi-*` per terminali
  minimali);
- **interfaccia it/en** (`--lang`), stringhe centralizzate in `app/tui/i18n.py`
  (le stringhe del motore restano in italiano, condivise con CLI/server);
- **fallback a wizard a righe** (`app/tui/fallback.py`) quando Textual manca o
  il terminale è minimo: stesse validazioni, stesso runner, stesso output;
- nuovo `probe_terminal()` (TTY, `TERM`, UTF-8, `NO_COLOR`, sfondo scuro) e
  flag `--ascii`.

Test: 387. e2e reali 3 run × 5 pagine (service e desktop sugli stessi PDF).
