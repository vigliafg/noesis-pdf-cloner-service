"""Seam email transazionali.

Oggi, se disabilitato, si limita a registrare l'email nella tabella ``emails``
(utile per test e per l'audit). In futuro si collegherà un provider SMTP/API.
"""

from __future__ import annotations

import logging

from .storage import Storage

log = logging.getLogger("noesis.email")

# Eventi previsti (predisposti per il commerciale futuro).
EVENT_JOB_DONE = "job_done"
EVENT_QUOTA_EXHAUSTED = "quota_exhausted"
EVENT_INVOICE = "invoice"


class Emailer:
    """Sender fittizio: salva su DB e logga (nessun invio reale)."""

    def __init__(self, storage: Storage, enabled: bool = False) -> None:
        self.storage = storage
        self.enabled = enabled

    def send(self, recipient: str, subject: str, body: str) -> None:
        status = "queued" if self.enabled else "logged"
        try:
            self.storage.add_email(recipient, subject, body, status=status)
        except Exception:  # pragma: no cover
            log.exception("salvataggio email fallito")
        if self.enabled:
            log.info("email in coda per %s: %s", recipient, subject)
        else:
            log.debug("email (dry-run) per %s: %s", recipient, subject)
