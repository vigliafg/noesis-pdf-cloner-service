"""Stima di tempo e costo per una selezione di pagine (prima dell'avvio).

Tempo
-----
Velocità media storica per motore (tabella ``usage``); se i dati sono
insufficienti ripiega sui default, sovrascrivibili con
``ESTIMATE_MS_PER_PAGE_<MOTORE>``.

Costo
-----
1. Se ``COST_CENTS_PER_PAGE_<MOTORE>`` è impostato, è usato come prezzo
   esplicito (es. prezzo commerciale) e vince su tutto.
2. Altrimenti, per il motore ``llm`` (LLM/OpenRouter), il costo è stimato dal testo
   sorgente con l'equazione calibrata::

       token_in  = (chars_sorgente / CHARS_PER_TOKEN) * LLM_OVERHEAD_FACTOR
       token_out = token_in * LLM_OUTPUT_RATIO
       costo_USD = token_in/1e6 * P_in + token_out/1e6 * P_out

   dove ``P_in``/``P_out`` sono i prezzi OpenRouter per milione di token e
   ``LLM_OVERHEAD_FACTOR`` cattura i prompt ripetuti per chunk da pdf2zh_next
   (calibrato empiricamente, vedi README "Stima del costo").
3. Per gli altri motori il costo è 0 (gratuiti / non configurati).
"""

from __future__ import annotations

from .config import Settings
from .engine import ENGINES, CloneEngine
from .models import DocumentRecord, EstimateOut, normalize_engine
from .storage import Storage

# Stime di default (ms/pagina) quando non c'è storico sufficiente.
DEFAULT_MS_PER_PAGE: dict[str, int] = {
    "google": 60_000,
    "bing": 50_000,
    "llm": 70_000,
}


def _sample_source_chars(pdf_path: str, pages: list[int], sample: int) -> float:
    """Media dei caratteri estraibili per pagina (campionando fino a ``sample``)."""
    if not pages:
        return 0.0
    try:
        import pymupdf
    except Exception:  # pragma: no cover
        return 0.0
    if len(pages) <= sample:
        chosen = pages
    else:
        step = (len(pages) - 1) / max(sample - 1, 1)
        chosen = sorted({pages[round(i * step)] for i in range(sample)})
    total = 0
    counted = 0
    try:
        with pymupdf.open(pdf_path) as doc:
            for page in chosen:
                if 0 <= page < doc.page_count:
                    total += len(doc[page].get_text("text"))
                    counted += 1
    except Exception:  # pragma: no cover
        return 0.0
    return total / counted if counted else 0.0


def _llm_cost_usd_per_page(avg_chars: float, settings: Settings) -> float:
    """Equazione di costo per pagina del motore LLM (USD)."""
    tokens_in = avg_chars / max(settings.chars_per_token, 0.1) * settings.llm_overhead_factor
    tokens_out = tokens_in * settings.llm_output_ratio
    return (
        tokens_in / 1_000_000 * settings.llm_price_prompt_per_mtok
        + tokens_out / 1_000_000 * settings.llm_price_completion_per_mtok
    )


def estimate_job(
    *,
    storage: Storage,
    settings: Settings,
    document: DocumentRecord,
    pages: list[int],
    engine: str,
    src_lang: str,
    dst_lang: str,
) -> EstimateOut:
    engine = normalize_engine(engine)
    if engine not in ENGINES:
        engine = "google"
    cache = CloneEngine(
        settings.cache_root,
        cache_version=settings.engine_cache_version,
        llm_model=settings.llm_model,
        llm_base_url=settings.llm_base_url,
        api_key=settings.openrouter_api_key,
    )
    cached = cache.cached_pages(
        document.sha256, pages, engine, src_lang, dst_lang
    )
    to_translate = len(pages) - len(cached)

    historical_ms, samples = storage.engine_speed(engine)
    override_ms = int(settings.estimate_ms_per_page.get(engine, 0) or 0)
    ms_per_page = override_ms or historical_ms or DEFAULT_MS_PER_PAGE.get(engine, 60_000)

    notes: list[str] = []
    if override_ms:
        notes.append("tempo: configurata")
    elif historical_ms:
        notes.append(f"tempo: storica su {samples} pagine")
    else:
        notes.append("tempo: default")
    notes.append(f"{len(cached)} pagine già in cache")

    rate = int(settings.cost_cents_per_page.get(engine, 0) or 0)
    currency = "EUR"
    if rate > 0:
        # Prezzo esplicito per pagina (commerciale).
        cost_cents = float(to_translate * rate)
        notes.append(f"costo: {rate} cent/pagina configurato")
    elif engine == "llm":
        currency = "USD"
        if to_translate == 0:
            cost_cents = 0.0
            notes.append("tutte le pagine sono in cache")
        else:
            avg_chars = _sample_source_chars(
                document.path, pages, settings.estimate_sample_pages
            )
            cost_usd = _llm_cost_usd_per_page(avg_chars, settings) * to_translate
            cost_cents = round(cost_usd * 100, 4)
            notes.append(
                f"costo: LLM {settings.llm_price_prompt_per_mtok}/"
                f"{settings.llm_price_completion_per_mtok} $/Mtok · "
                f"overhead {settings.llm_overhead_factor:g}× · "
                f"~{avg_chars:.0f} char/pagina"
            )
    else:
        cost_cents = 0.0
        notes.append("motore senza costo configurato")

    return EstimateOut(
        doc_id=document.doc_id,
        engine=engine,
        src_lang=src_lang,
        dst_lang=dst_lang,
        pages_total=len(pages),
        pages_cached=len(cached),
        pages_to_translate=to_translate,
        ms_per_page=ms_per_page,
        estimated_seconds=int(to_translate * ms_per_page / 1000),
        cost_cents=cost_cents,
        currency=currency,
        note=" · ".join(notes),
    )
