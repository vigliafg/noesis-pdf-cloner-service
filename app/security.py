"""Sicurezza applicativa: sanitizzazione nomi, rate limit, validazione upload."""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import defaultdict, deque
from pathlib import Path

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED = {".", ".."}


def sanitize_stem(name: str | None, default: str = "output") -> str:
    """Riduce ``name`` a uno stem di file sicuro (niente path traversal).

    Accetta nomi con o senza estensione ``.pdf``. Rimuove separatori e
    caratteri non sicuri; garantisce un risultato non vuoto.
    """
    raw = (name or "").strip()
    if raw.lower().endswith(".pdf"):
        raw = raw[:-4]
    raw = unicodedata.normalize("NFKD", raw)
    raw = raw.encode("ascii", "ignore").decode("ascii")
    raw = _SAFE_RE.sub("_", raw).strip("._-")
    if not raw or raw in _RESERVED:
        return default
    return raw[:120]


def validate_pdf_upload(filename: str | None, size_bytes: int, max_mb: int) -> None:
    """Controlli minimi su nome/dimensione; solleva ``ValueError`` se invalido."""
    if not filename:
        raise ValueError("nome file mancante")
    if not filename.lower().endswith(".pdf"):
        raise ValueError("sono accettati solo file .pdf")
    if size_bytes <= 0:
        raise ValueError("file vuoto")
    if max_mb and size_bytes > max_mb * 1024 * 1024:
        raise ValueError(f"file troppo grande (max {max_mb} MB)")


class RateLimiter:
    """Rate limiter in-memory a finestra scorrevole, per chiave (IP/actor).

    Sufficiente per un singolo processo; in un futuro multi-nodo andrà
    sostituito con uno store condiviso (Redis) dietro la stessa interfaccia.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(1, per_minute)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        window_start = now - 60.0
        with self._lock:
            events = self._events[key]
            while events and events[0] < window_start:
                events.popleft()
            if len(events) >= self.per_minute:
                return False
            events.append(now)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            events = self._events.get(key)
            if not events:
                return 0
            return max(1, int(60 - (time.monotonic() - events[0])))


def safe_join(base: Path, *parts: str) -> Path:
    """Join che garantisce che il risultato resti dentro ``base``."""
    candidate = base.joinpath(*parts).resolve()
    root = base.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("percorso non consentito")
    return candidate
