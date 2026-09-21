# PDF.js (opzionale, per l'anteprima lato client)

L'anteprima della pagina (o della prima/ultima del range) funziona **sempre**
tramite l'endpoint server `/api/v1/documents/{id}/thumb` (PyMuPDF), quindi non
è necessario installare nulla.

Per abilitare anche il rendering **lato client** (istantaneo, dal file locale,
senza round-trip) basta collocare qui la build di PDF.js:

```
app/static/vendor/pdfjs/pdf.min.mjs
app/static/vendor/pdfjs/pdf.worker.min.mjs
```

`app.js` rileva automaticamente la presenza di `pdf.min.mjs` e, se c'è, la usa
come enhancement; altrimenti ripiega sulle miniature del server.
