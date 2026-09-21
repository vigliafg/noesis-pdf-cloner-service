"""Parsing della specifica pagine scelta dall'utente.

Formati accettati (1-based, come li vede l'utente):

- ``all``                     → tutte le pagine
- ``7``                       → la pagina 7
- ``100-103``                 → l'intervallo 100..103 (estremi invertiti ok)
- ``3,5,10-12``               → lista mista
- ``1, 3 , 5-7``              → spazi ignorati

La funzione ritorna indici **0-based**, ordinati e senza duplicati: è la
convenzione usata dal motore (vedi la lezione del bug off-by-one del desktop).
"""

from __future__ import annotations

__all__ = ["parse_pages", "format_pages_label", "describe_pages"]

_MAX_PAGES = 100_000


def _parse_token(token: str, page_count: int) -> list[int]:
    token = token.strip()
    if not token:
        raise ValueError("specifica pagine vuota")
    if "-" in token:
        left, _, right = token.partition("-")
        try:
            start = int(left.strip())
            end = int(right.strip())
        except ValueError as exc:
            raise ValueError(f"intervallo non valido: '{token}'") from exc
        if start > end:
            start, end = end, start
        _check_bound(start, page_count)
        _check_bound(end, page_count)
        return list(range(start - 1, end))
    try:
        page = int(token)
    except ValueError as exc:
        raise ValueError(f"numero di pagina non valido: '{token}'") from exc
    _check_bound(page, page_count)
    return [page - 1]


def _check_bound(page: int, page_count: int) -> None:
    if page < 1:
        raise ValueError("le pagine partono da 1")
    if page_count and page > page_count:
        raise ValueError(f"pagina {page} oltre il totale ({page_count})")


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    """Converte la specifica utente in indici 0-based ordinati e unici.

    Solleva ``ValueError`` per specifiche non valide o fuori intervallo.
    """
    if page_count <= 0:
        raise ValueError("il documento non contiene pagine")
    text = (spec or "all").strip().lower()
    if text in {"", "all", "*"}:
        return list(range(page_count))
    pages: set[int] = set()
    for chunk in text.split(","):
        pages.update(_parse_token(chunk, page_count))
    if not pages:
        raise ValueError("nessuna pagina selezionata")
    if len(pages) > _MAX_PAGES:
        raise ValueError("troppe pagine richieste")
    return sorted(pages)


def format_pages_label(pages: list[int]) -> str:
    """Etichetta compatta per il nome file: "156" oppure "100-103"."""
    if not pages:
        return ""
    ordered = sorted(pages)
    if len(ordered) == 1:
        return str(ordered[0] + 1)
    # Intervallo contiguo → "a-b"; altrimenti elenco con virgole.
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0] + 1}-{ordered[-1] + 1}"
    return ",".join(str(p + 1) for p in ordered)


def describe_pages(pages: list[int]) -> str:
    """Descrizione leggibile per il log/anteprima."""
    if not pages:
        return "nessuna pagina"
    if len(pages) == 1:
        return f"pagina {pages[0] + 1}"
    return f"{len(pages)} pagine ({format_pages_label(pages)})"
