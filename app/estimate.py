"""Stima di tempo e costo per una selezione di pagine (prima dell'avvio).

La stima di tempo usa la velocità media storica per motore (tabella ``usage``);
se i dati sono insufficienti ripiega su valori di default, eventualmente
sovrascritti da ``ESTIMATE_MS_PER_PAGE_<MOTORE>``. Il costo usa
``COST_CENTS_PER_PAGE_<MOTORE>`` (0 = gratis / best-effort).
"""

from __future__ import annotations

from .config import Settings
from .engine import ENGINES, CloneEngine
from .models import DocumentRecord, EstimateOut
from .storage import Storage

# Stime di default (ms/pagina) quando non c'è storico sufficiente.
DEFAULT_MS_PER_PAGE: dict[str, int] = {
    "google": 60_000,
    "bing": 50_000,
    "openai": 70_000,
}


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
    override = int(settings.estimate_ms_per_page.get(engine, 0) or 0)
    ms_per_page = override or historical_ms or DEFAULT_MS_PER_PAGE.get(engine, 60_000)

    rate = int(settings.cost_cents_per_page.get(engine, 0) or 0)
    cost_cents = to_translate * rate

    if override:
        source = "configurata"
    elif historical_ms:
        source = f"storica su {samples} pagine"
    else:
        source = "default"
    notes = [f"stima {source}", f"{len(cached)} pagine già in cache"]
    if rate == 0:
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
        currency="EUR",
        note=" · ".join(notes),
    )
