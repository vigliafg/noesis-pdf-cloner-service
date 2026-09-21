"""Dipendenze comuni alle route API."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ...context import AppContext


def get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:  # pragma: no cover - app sempre inizializzata
        raise HTTPException(status_code=503, detail="servizio non inizializzato")
    return ctx
