# Componenti di terze parti e asset · Third-party components and assets

Questo documento integra [`NOTICE`](NOTICE) e traccia **tutti** i componenti e gli
asset ridistribuiti, in particolare quelli inclusi nell'**immagine Docker**.

## Componenti a runtime (Python)

| Componente | Licenza | Note |
|---|---|---|
| FastAPI / Starlette / Uvicorn | MIT / BSD | API e server |
| Jinja2 | BSD-3-Clause | template |
| pydantic | MIT | modelli |
| python-multipart | Apache-2.0 | upload |
| **PyMuPDF** (`pymupdf`) | **AGPL-3.0** o commerciale Artifex | split, thumbnail, `/PageLabels` |
| tqdm | MIT / MPL-2.0 | barra CLI |
| Markdown (Python-Markdown) | BSD-3-Clause | pagine legali |

## Motore (venv `.venv2`)

| Componente | Licenza | Note |
|---|---|---|
| **pdf2zh_next** | **AGPL-3.0** | invocato come `subprocess` |
| **BabelDOC** | **AGPL-3.0** | typesetter |
| dipendenze di pdf2zh_next/BabelDOC | varie (MIT/BSD/Apache, ecc.) | vedi `requirements-engine.lock` |

## Asset scaricati da `babeldoc --warmup` e presenti nell'immagine

Inventario verificato sulla cache `~/.cache/babeldoc` (≈337 MB):

### Font (34 file, 8 famiglie)

| Famiglia | File | Licenza | Ridistribuibile |
|---|---|---|---|
| **Noto Sans** | 4 | SIL OFL-1.1 (Google) | ✅ con testo OFL |
| **Noto Serif** | 4 | SIL OFL-1.1 (Google) | ✅ con testo OFL |
| **Source Han Sans** (CN/HK/JP/KR/TW) | 10 | SIL OFL-1.1 (Adobe/Google) | ✅ con testo OFL |
| **Source Han Serif** (CN/HK/JP/KR/TW) | 10 | SIL OFL-1.1 (Adobe/Google) | ✅ con testo OFL |
| **Klee One** (`KleeOne-Regular`) | 1 | SIL OFL-1.1 (Fontworks) | ✅ con testo OFL |
| **LXGW WenKai** (GB/TC) | 2 | SIL OFL-1.1 | ✅ con testo OFL |
| **MaruBuri** | 1 | SIL OFL-1.1 (NAVER) | ✅ con testo OFL |
| **Go Noto Kurrent** (`GoNotoKurrent-Regular/Bold`) | 2 | **non dichiarata** (fusione di font Noto) | ⚠️ da chiarire |

Testo della licenza OFL incluso in [`licenses/OFL-1.1.txt`](licenses/OFL-1.1.txt).
**Obblighi OFL:** includere il testo licenza e le note di copyright; **non** vendere
i font da soli; rispettare i *Reserved Font Name* (non rinominare i font).

### Modello di layout

| Asset | Dimensione | Licenza | Note |
|---|---|---|---|
| `doclayout_yolo_docstructbench_imgsz1024.onnx` | 72 MB | **AGPL-3.0** (vedi nota) | layout detection |

Fonte: `wybxc/DocLayout-YOLO-DocStructBench-onnx` (Hugging Face) ←
`opendatalab/DocLayout-YOLO`.
**Nota/ambiguità:** il repo upstream DocLayout-YOLO è **AGPL-3.0**; la
conversione ONNX dichiara **Apache-2.0**. Per prudenza va trattato come
**AGPL-3.0** (deriva da un modello AGPL/"Ultralytics YOLO"). Compatibile col
progetto (anch'esso AGPL-3.0), ma va attribuito e incluso nell'offerta del
sorgente.

### Altro

| Asset | Licenza | Note |
|---|---|---|
| **cmap** (Adobe cmap-resources) | BSD-3-Clause | decodifica CJK |
| **tiktoken** (encoding) | MIT (OpenAI) | conteggio token |
| `ghcr.io/astral-sh/uv` | MIT / Apache-2.0 | solo in build, pinnato per digest |

## Da chiarire (follow-up)

1. **Go Noto Kurrent**: licenza non dichiarata dal progetto
   `satbyy/go-noto-universal` (GitHub riporta "NOASSERTION"). Trattandosi di una
   fusione di font **Noto** (OFL), è probabilmente OFL, ma va **confermato o
   sostituito** prima di un uso commerciale.
2. **Modello ONNX**: confermare la licenza effettiva (AGPL-3.0 vs Apache-2.0) o
   documentare l'assunzione prudenziale AGPL-3.0.
3. **Aggiornamento inventario**: rieseguire la verifica quando BabelDOC cambia
   versione (gli asset sono scaricati in build).

## Verifica automatica

```bash
.venv2/bin/babeldoc --warmup
find ~/.cache/babeldoc -maxdepth 2 -type d
ls ~/.cache/babeldoc/fonts
```
