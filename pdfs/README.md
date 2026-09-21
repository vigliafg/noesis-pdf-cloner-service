# pdfs/ — PDF di test

Questa cartella contiene i **PDF usati per i test** (es. `ha22.pdf`, `ce24.pdf`,
`co23.pdf`, …).

I file `*.pdf` **non sono versionati** (copyright e dimensioni: fino a ~300 MB
ciascuno) — vedi `.gitignore`. Restano quindi **solo in locale**.

Per usarli negli esempi:

```bash
./run-cli.sh pdfs/ha22.pdf -p 156 --dst it --engine google --output prova
```

Per caricare un PDF nel servizio:

```bash
curl -s -F "file=@pdfs/ha22.pdf" http://127.0.0.1:18080/api/v1/documents
```
