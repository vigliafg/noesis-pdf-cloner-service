# Installazione — `noesis` (console unica)

Un solo punto di ingresso per **Linux · macOS · WSL · Windows nativo**:
la console `noesis` (Python, sola libreria standard) crea i venv, installa il
motore, scrive la configurazione, installa il servizio e diagnostica i problemi.

```
install.sh / install.ps1        gusci: delegano alla console
bootstrap.sh                    opzionale: clona il repo e installa
        │
        ▼
tools/noesis.py                 unica fonte di verità
   install · start · stop · restart · status · logs
   doctor · open · service · bundle · update · uninstall
```

## Requisiti

- **Linux / macOS / WSL**: `bash` e `curl` (la console installa `uv`, che a sua
  volta scarica Python 3.12).
- **Windows nativo**: PowerShell (per installare `uv`).
- `git` (per clonare/aggiornare), **internet** in uscita (dipendenze, modelli,
  traduzioni).
- Nessun privilegio di root: il servizio è **utente** (systemd user / launchd /
  Task Scheduler). Serve `sudo` solo se apri il firewall con `--open-firewall`.

## Installazione rapida

```bash
git clone https://github.com/vigliafg/noesis-pdf-cloner-service
cd noesis-pdf-cloner-service
./install.sh
```

Con il **bootstrap** (repo pubblico), in un colpo solo:

```bash
curl -LsSf https://raw.githubusercontent.com/vigliafg/noesis-pdf-cloner-service/main/bootstrap.sh | bash
```

A fine installazione la console stampa gli URL (locale + LAN) e, se c'è una
sessione grafica, apre il browser.

## Comandi del cruscotto

| Comando | Cosa fa |
|---|---|
| `./noesis install` | venv + motore + config + servizio + pre-warm |
| `./noesis start` / `stop` / `restart` | avvia/ferma/riavvia in background |
| `./noesis status` | processo, `/api/v1/health` e stato del servizio |
| `./noesis logs -n 100` | ultime righe di log |
| `./noesis doctor` | diagnosi completa (cosa manca e perché) |
| `./noesis open` | apre il frontend nel browser |
| `./noesis service install\|uninstall\|status` | gestione del servizio |
| `./noesis bundle` | crea un pacchetto **offline** |
| `./noesis update` | `git pull` + aggiorna le dipendenze |
| `./noesis uninstall [--all]` | rimuove il servizio; scelta interattiva di cosa rimuovere |

Opzioni utili: `--data-dir`, `--host`, `--port`, `--mode user|system`,
`--no-service`, `--no-engine`, `--skip-warm`, `--open-firewall`, `--dry-run`,
`--json`, `--ci`.

## Configurazione

File unico: **`<data_dir>/noesis.env`** (stesse variabili lette
dall'applicazione, vedi il README). La cartella dati di default è quella
standard dell'OS:

| OS | Cartella dati |
|---|---|
| Linux / WSL | `~/.local/share/noesis-pdf-cloner-service` |
| macOS | `~/Library/Application Support/noesis-pdf-cloner-service` |
| Windows | `%LOCALAPPDATA%\noesis-pdf-cloner-service` |

Precedenza: **opzione CLI > variabile d'ambiente della shell > `noesis.env` >
default**. I segreti (`OPENROUTER_API_KEY`) vanno **solo** qui o nell'ambiente,
mai nel codice.

## Standalone e LAN

`HOST=0.0.0.0` (default) copre **entrambi**: in locale usi
`http://127.0.0.1:18080`, in LAN `http://<ip-della-macchina>:18080`.

- Per la LAN potrebbe servire aprire la porta 18080: `./noesis install --open-firewall`
  (rileva `ufw`/`firewalld`; su Windows richiede un terminale amministratore).
- `./noesis doctor` spiega ogni blocco, **incluso WSL**: da WSL la porta non è
  visibile in LAN senza `networkingMode=mirrored` (Windows 11) o un `portproxy`.
  In locale su WSL funziona comunque.

## Servizio e avvio automatico

`install` installa e abilita il servizio (avvio automatico):

| OS | Meccanismo |
|---|---|
| Linux | **systemd user** (`~/.config/systemd/user/`), con `enable-linger` |
| macOS | **launchd** (`~/Library/LaunchAgents/`) |
| Windows | **Task Scheduler** (all'accesso) |
| WSL senza systemd | avvio in background; `doctor` spiega come abilitare systemd |

- `--mode system` usa il servizio di sistema (richiede root): predisposto per il
  futuro deploy su VPS.
- `--no-service` fa solo il setup e non tocca il sistema.

## Windows

- **WSL2** (consigliato): esegui `./install.sh` **dentro** la distro Linux.
- **Nativo** (best effort): `.\install.ps1` (o `.\noesis.cmd install`).

## Bundle offline (installazione su più macchine)

Su una macchina già installata:

```bash
./noesis bundle                       # crea dist/noesis-bundle-<os>-<arch>.tar.gz
```

Su un'altra macchina (stessa **OS + architettura**), con il repo clonato:

```bash
./noesis install --bundle /percorso/noesis-bundle-<os>-<arch>.tar.gz
```

Il bundle contiene i **wheel** (servizio + motore) e i **modelli** del motore:
l'installazione avviene **senza rete**, in pochi minuti. Serve un bundle per
piattaforma (Linux x86_64 ≠ macOS arm64 ≠ Windows).

## Aggiornamento e disinstallazione

```bash
./noesis update                 # git pull + dipendenze
./noesis uninstall              # scelta interattiva di cosa rimuovere (solo servizio in non-TTY)
./noesis uninstall --dry-run    # piano con dimensioni, nessuna modifica
./noesis uninstall --data       # rimuove servizio + dati (alias storico: --purge)
./noesis uninstall --venv       # rimuove anche il venv del servizio (.venv)
./noesis uninstall --engine     # rimuove anche il motore (.venv2) e la cache BabelDOC
./noesis uninstall --all -y     # nessuna traccia del servizio (venv + motore + dati + cache)
```

Su terminale `uninstall` mostra il menu **"Cosa rimuovere"** con le dimensioni e
chiede conferma; senza TTY (o con `--json`/`--yes`) è conservativo. La cache
condivisa di `uv`/Python gestiti **non viene mai toccata**; il repository non
viene mai rimosso.

Wrapper equivalenti: `./uninstall.sh` (Linux/macOS/WSL) e `.\uninstall.ps1`
(Windows) delegano a `./noesis uninstall`.

## Diagnosi

Se qualcosa non va, `./noesis doctor` è il primo posto da guardare: controlla
piattaforma, uv, venv, motore, config, cartella dati, spazio, server, firewall,
font e URL. `--json` per l'automazione, `--strict` per uscire con errore anche
sugli avvisi.

## VPS (futuro)

La console è già predisposta: `--mode system` e i bordi di configurazione
esistono. Il deploy su VPS (nginx/TLS/auth) resta una fase successiva.
