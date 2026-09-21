"""Seam audit log: registra le azioni rilevanti (chi ha fatto cosa).

Attivo da subito (scrive nella tabella ``audit``) ma a impatto nullo sul flusso.
"""

from __future__ import annotations

import logging

from .auth import Actor
from .storage import Storage

log = logging.getLogger("noesis.audit")


def record(
    storage: Storage,
    actor: Actor | None,
    action: str,
    resource: str | None = None,
    meta: dict | None = None,
) -> None:
    """Registra un evento di audit; non solleva mai eccezioni."""
    actor_id = actor.id if actor else None
    try:
        storage.add_audit(
            actor_id=actor_id, action=action, resource=resource, meta=meta or {}
        )
    except Exception:  # pragma: no cover - l'audit non deve rompere il flusso
        log.exception("scrittura audit fallita per %s", action)
