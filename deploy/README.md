# Deploy su VPS (systemd + nginx)

> **Nota**: per l'installazione su una macchina personale o in LAN usa la console
> `./noesis install` (vedi [`../docs/INSTALL.md`](../docs/INSTALL.md)): crea venv,
> config e servizio da sola. Le unit qui sotto restano per il **deploy manuale**
> e per il futuro **VPS** (`--mode system`).

Schema consigliato su **un VPS scalabile**:

```
nginx (TLS, upload, SSE)  ─►  noesis-api        (ROLE=api, 1..N processi uvicorn)
                                   │
                                   ▼
                         coda su SQLite (DATA_DIR condiviso)
                                   ▲
                                   │  claim atomico
        noesis-worker@1 .. @N  ────┘        (ROLE=worker, dati+motore)
```

L'API **non esegue** job: li accoda soltanto. I **worker** li reclamano dalla coda
condivisa. Aggiungere un worker = avviare un'altra unità.

## 1. Utente e cartelle

```bash
sudo useradd --system --create-home --home-dir /opt/noesis-pdf-cloner-service noesis
sudo mkdir -p /var/lib/noesis-pdf-cloner /etc/noesis
sudo chown -R noesis:noesis /var/lib/noesis-pdf-cloner /opt/noesis-pdf-cloner-service
```

## 2. Codice, venv e motore

```bash
sudo -u noesis git clone https://github.com/vigliafg/noesis-pdf-cloner-service \
    /opt/noesis-pdf-cloner-service
cd /opt/noesis-pdf-cloner-service
sudo -u noesis ./setup_engine.sh      # crea .venv2 e installa pdf2zh_next
```

## 3. Configurazione

```bash
sudo cp deploy/noesis.env.example /etc/noesis/noesis.env
sudo nano /etc/noesis/noesis.env      # OPENROUTER_API_KEY, DATA_DIR, WORKER_COUNT...
sudo chmod 600 /etc/noesis/noesis.env
```

`WORKER_COUNT` deve essere il **numero totale di worker** che avvierai: ogni
processo divide CPU/RAM per quel numero (autosizing).

## 4. Servizi

```bash
sudo cp deploy/noesis-api.service /etc/systemd/system/
sudo cp deploy/noesis-worker@.service /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable --now noesis-api
# avvia 4 worker (con WORKER_COUNT=4 in noesis.env)
sudo systemctl enable --now noesis-worker@1 noesis-worker@2 \
     noesis-worker@3 noesis-worker@4
```

Verifica: `curl -s localhost:18080/api/v1/health`, `curl -s localhost:18080/api/v1/system`.

## 5. nginx

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/noesis.conf
sudo ln -s /etc/nginx/sites-available/noesis.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Scalare / ridimensionare il VPS

- **Verticale**: fai resize del VPS e riavvia i servizi → l'autosizing ricalcola
  worker/concorrenza/processi motore.
- **Orizzontale (worker)**: aumenta `WORKER_COUNT` e avvia altre istanze
  `noesis-worker@N`; le risorse sono divise automaticamente.
- **API**: in `ROLE=api` puoi alzare `UVICORN_WORKERS` (l'API non tocca la coda
  dei job, solo lo scheduler dei job programmati).

## Note

- **DATA_DIR condiviso**: tutti i processi devono puntare alla stessa cartella
  (coda SQLite + cache condivisa). Su più nodi serve un filesystem condiviso.
- **Cache condivisa**: i worker riusano le traduzioni già presenti.
- **Ordine di spegnimento**: ferma prima i worker (`systemctl stop noesis-worker@*`),
  che concludono/interrompono i job in corso, poi l'API.
