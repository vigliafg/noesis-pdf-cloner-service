"""Accesso alla configurazione: chi è "locale" e può amministrare il servizio.

La pagina ``/settings`` e le sue API sono riservate a chi sta **sulla macchina
che ospita il servizio**. Il riconoscimento è automatico e non richiede
configurazione:

* ``127.0.0.1`` / ``::1`` → installazione nativa (console/systemd);
* il **gateway del container** (es. ``172.17.0.1``) → Docker: è l'indirizzo con
  cui il browser dell'host vede il servizio attraverso il NAT di Docker, quindi
  resta "locale" senza dover configurare nulla;
* ``ADMIN_ALLOW_FROM`` (opzionale, avanzato) → IP, CIDR o nomi extra;
* le richieste che arrivano da un **reverse proxy** (con ``X-Forwarded-For`` /
  ``X-Real-IP`` / ``Forwarded``) sono **rifiutate**: un proxy sullo stesso host
  farebbe sembrare remoti gli utenti come locali.

Solo standard library: la usa sia l'API sia il rendering della home.
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
from pathlib import Path
from typing import Mapping

__all__ = [
    "is_local_client",
    "container_gateway",
    "allowed_extra",
    "PROXY_HEADERS",
]

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")


@lru_cache(maxsize=1)
def container_gateway() -> str | None:
    """Gateway di default visto dentro un container (da ``/proc/net/route``)."""
    try:
        lines = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 3 or fields[1] != "00000000":  # Destination 0.0.0.0
            continue
        try:
            raw = bytes.fromhex(fields[2])
        except ValueError:
            continue
        if len(raw) != 4:
            continue
        # Gli indirizzi in /proc/net/route sono in little-endian.
        return ".".join(str(byte) for byte in reversed(raw))
    return None


def allowed_extra() -> tuple[str, ...]:
    """Regole extra da ``ADMIN_ALLOW_FROM`` (separate da virgola)."""
    raw = os.environ.get("ADMIN_ALLOW_FROM", "")
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def _normalize(host: str | None) -> str:
    host = (host or "").strip().lower()
    if host.startswith("::ffff:"):  # IPv4 mappato in IPv6
        host = host[len("::ffff:"):]
    return host


def _matches(host: str, rule: str) -> bool:
    if not rule:
        return False
    if rule == host:
        return True
    try:
        network = ipaddress.ip_network(rule, strict=False)
    except ValueError:
        return False  # non è un IP/CIDR: vale solo il confronto esatto
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address in network


def is_local_client(
    host: str | None, headers: Mapping[str, str] | None = None
) -> bool:
    """True se la richiesta arriva dalla macchina che ospita il servizio."""
    header_names = {str(key).lower() for key in (headers or {})}
    if any(name in header_names for name in PROXY_HEADERS):
        return False
    normalized = _normalize(host)
    if not normalized:
        return False
    if normalized in LOOPBACK:
        return True
    gateway = container_gateway()
    if gateway and normalized == gateway:
        return True
    return any(_matches(normalized, rule) for rule in allowed_extra())
