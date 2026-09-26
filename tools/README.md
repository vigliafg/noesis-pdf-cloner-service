# `tools/` — utilità del servizio

## `provider_proxy.py` — pin del provider LLM (model-aware)

`pdf2zh_next` non espone il routing del provider: per forzare Groq su OpenRouter
serve il campo `provider` nel body. Il proxy lo inietta **solo** per i modelli
scelti (`PROXY_MODELS`, default `openai/gpt-oss-120b`; `*` = tutti), lasciando
passare invariati gli altri modelli (DeepSeek, Gemini, Mercury…).

```bash
PROXY_PORT=8790 .venv/bin/python tools/provider_proxy.py    # in background
PDF_LLM_BASE_URL=http://127.0.0.1:8790/v1 \
PDF_LLM_MODEL=openai/gpt-oss-120b \
FAST_ENGINE=1 FAST_FLAGS=1 FAST_WORKER=1 ./run-cli.sh libro.pdf
```

Variabili: `PROXY_PORT`, `PROXY_PROVIDER` (default `groq`), `PROXY_MODELS`,
`PROXY_UPSTREAM`, `OPENROUTER_API_KEY`. Solo stdlib.

Nota: in alternativa esiste l'allowlist account-wide di OpenRouter
(Settings → Privacy → Allowed Providers), ma è **globale** e blocca tutti gli
altri provider/modelli; scartata a favore del proxy per-richiesta.

Allineato al desktop `noesis-pdf-cloner` (stessa feature `fast_engine`).
