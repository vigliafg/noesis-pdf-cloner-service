"""Seam di identità.

Oggi il servizio è anonimo: ``get_current_actor`` identifica il visitatore con
un cookie (o header) opaco e non applica alcun controllo. In futuro basterà
impostare ``AUTH_MODE``:

- ``none``  → anonimo (default);
- ``proxy`` → si fidano gli header di un reverse proxy autenticato
              (oauth2-proxy/Keycloak), con ``TRUSTED_PROXY_HEADERS=true``;
- ``jwt``   → verifica di un JWT (Supabase/OIDC): da implementare (seam).

Il resto dell'applicazione usa solo :class:`Actor` e ``authorize``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from .config import Settings

ANON_COOKIE = "noesis_client"
CLIENT_HEADER = "X-Client-Id"
_PROXY_HEADER = "X-Auth-Request-User"
_PROXY_EMAIL = "X-Auth-Request-Email"


@dataclass(frozen=True)
class Actor:
    id: str
    kind: str = "anonymous"  # anonymous | user | admin
    name: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.kind in {"user", "admin"}

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"


def _anonymous(request: Request, response: Response) -> Actor:
    client_id = request.cookies.get(ANON_COOKIE) or request.headers.get(
        CLIENT_HEADER
    )
    if not client_id:
        client_id = uuid.uuid4().hex
        try:
            response.set_cookie(
                ANON_COOKIE,
                client_id,
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 24 * 365,
            )
        except (RuntimeError, AttributeError):
            # fuori da un contesto di risposta (es. test): ignora
            pass
    return Actor(id=f"anonymous:{client_id}", kind="anonymous")


def _from_proxy(request: Request, settings: Settings) -> Actor | None:
    if not settings.trusted_proxy_headers:
        return None
    subject = request.headers.get(_PROXY_HEADER)
    if not subject:
        return None
    email = request.headers.get(_PROXY_EMAIL)
    return Actor(id=f"user:{subject}", kind="user", name=email or subject)


def actor_from_request(
    request: Request, response: Response, settings: Settings
) -> Actor:
    """Risolve l'attore senza sollevare eccezioni (logica pura)."""
    if settings.auth_mode == "proxy":
        actor = _from_proxy(request, settings)
        if actor is not None:
            return actor
    elif settings.auth_mode == "jwt":
        # Seam: la verifica JWT (Supabase/OIDC) verrà implementata qui.
        raise HTTPException(
            status_code=501,
            detail="AUTH_MODE=jwt non ancora implementato (seam futuro)",
        )
    return _anonymous(request, response)


def get_current_actor(request: Request, response: Response) -> Actor:
    """Dipendenza FastAPI: attore corrente (anonimo di default)."""
    from .config import get_settings

    return actor_from_request(request, response, get_settings())


def authorize(actor: Actor, owner_id: str | None) -> None:
    """Verifica di proprietà.

    Oggi è un no-op (i dati anonimi sono accessibili per id non indovinabile).
    Quando l'auth sarà attiva basterà confrontare ``actor.id`` con ``owner_id``.
    """
    return None
