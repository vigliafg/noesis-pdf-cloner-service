"""Configurazione del servizio via web (solo dalla macchina locale).

Espone lo **schema** delle impostazioni e i loro **valori effettivi**, e
permette di modificarli scrivendo ``<data_dir>/noesis.env``. Le modifiche si
applicano **al riavvio** (``Settings`` è letto all'avvio): la risposta lo dice
esplicitamente.

Regole di sicurezza:

* accesso riservato a chi è "locale" (vedi :mod:`app.admin`), incluso il gateway
  del container Docker; i proxy sono rifiutati;
* i **segreti** (es. ``OPENROUTER_API_KEY``) non vengono **mai** restituiti: si
  può solo sapere se sono presenti e scriverne uno nuovo;
* le chiavi di deploy (``HOST``, ``PORT``, ``ROLE``, ...) non sono modificabili
  dal web.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...admin import is_local_client
from ...config import Settings
from ...diagnostics import (
    CheckResult,
    Status,
    check_key_credits,
    check_key_valid,
    check_llm_model,
)
from ...envfile import (
    InvalidValue,
    config_path,
    group_specs,
    load_env_file,
    save_env_file,
    spec_by_name,
    validate_value,
)
from .deps import get_ctx

router = APIRouter(tags=["settings"])


def require_local_admin(request: Request) -> None:
    """Dipendenza: consente solo richieste provenienti dalla macchina locale."""
    host = request.client.host if request.client else None
    if not is_local_client(host, request.headers):
        raise HTTPException(
            status_code=403,
            detail=(
                "La configurazione è disponibile solo dal computer che ospita "
                "il servizio."
            ),
        )


# ── modelli ─────────────────────────────────────────────────────────────────


class SettingsUpdate(BaseModel):
    """Modifiche richieste: nuovi valori e chiavi da rimuovere."""

    values: dict[str, str] = Field(default_factory=dict)
    reset: list[str] = Field(default_factory=list)


class CheckOut(BaseModel):
    id: str
    status: str
    code: str = "ok"
    message: str = ""
    fix: str = ""


class VerifyKeyOut(BaseModel):
    status: str
    key_valid: CheckOut
    credits: CheckOut
    model: CheckOut
    model_name: str


# ── helper ──────────────────────────────────────────────────────────────────


def _to_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _effective(settings: Settings, spec) -> str:
    """Valore effettivo dell'impostazione (dal processo in esecuzione)."""
    if spec.field is None:
        return ""
    value = getattr(settings, spec.field, "")
    if spec.index is not None:
        value = (value or {}).get(spec.index, "")
    return _to_str(value)


def _stored_key(settings: Settings) -> str:
    """Chiave del server secondo i ``Settings`` (già fusi con l'ambiente)."""
    return (settings.openrouter_api_key or "").strip()


def _setting_payload(settings: Settings, spec, file_values: dict[str, str]) -> dict:
    payload = {
        "name": spec.name,
        "kind": spec.kind,
        "group": spec.group,
        "secret": spec.secret,
        "restart_required": spec.restart_required,
        "desc_it": spec.desc_it,
        "desc_en": spec.desc_en,
        "default": spec.default,
        "minimum": spec.minimum,
        "maximum": spec.maximum,
        "choices": list(spec.choices),
        "in_file": spec.name in file_values,
        "env_override": spec.name in settings.shell_env_keys,
    }
    if spec.secret:
        payload["value"] = None
        payload["present"] = bool(_stored_key(settings))
    else:
        payload["value"] = _effective(settings, spec)
        payload["present"] = None
    return payload


# ── endpoint ────────────────────────────────────────────────────────────────


@router.get("/settings", dependencies=[Depends(require_local_admin)])
def read_settings(request: Request) -> dict:
    """Schema + valori effettivi delle impostazioni (segreti esclusi)."""
    ctx = get_ctx(request)
    settings = ctx.settings
    path = config_path(settings.data_dir)
    file_values = load_env_file(path)

    groups = []
    for group_id, title_it, title_en, specs in group_specs(web_only=True):
        groups.append({
            "id": group_id,
            "title_it": title_it,
            "title_en": title_en,
            "settings": [
                _setting_payload(settings, spec, file_values) for spec in specs
            ],
        })

    return {
        "config_path": str(path),
        "restart_required": True,
        "key_present": bool(_stored_key(settings)),
        "groups": groups,
    }


def _resolve_web_spec(name: str):
    spec = spec_by_name(name)
    if spec is None:
        raise HTTPException(status_code=422, detail=f"impostazione sconosciuta: {name}")
    if not spec.web_editable:
        raise HTTPException(
            status_code=403,
            detail=f"{spec.name} non è modificabile dal web (usa la riga di comando)",
        )
    return spec


@router.put("/settings", dependencies=[Depends(require_local_admin)])
def update_settings(request: Request, payload: SettingsUpdate) -> dict:
    """Valida e salva le modifiche in ``noesis.env`` (valide al riavvio)."""
    ctx = get_ctx(request)
    settings = ctx.settings
    path = config_path(settings.data_dir)

    updates: dict[str, str] = {}
    removals: list[str] = []

    for name, raw in payload.values.items():
        spec = _resolve_web_spec(name)
        try:
            normalized = validate_value(spec, raw)
        except InvalidValue as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # Un segreto svuotato significa "rimuovilo".
        if spec.secret and not normalized:
            removals.append(spec.name)
        else:
            updates[spec.name] = normalized

    for name in payload.reset:
        spec = _resolve_web_spec(name)
        removals.append(spec.name)

    if updates or removals:
        save_env_file(path, updates, remove=removals)

    return {
        "saved": sorted(updates),
        "removed": sorted(set(removals)),
        "restart_required": True,
        "config_path": str(path),
    }


@router.post("/settings/verify-key", dependencies=[Depends(require_local_admin)])
def verify_stored_key(request: Request) -> VerifyKeyOut:
    """Verifica la chiave del server (chiave, credito, modello)."""
    ctx = get_ctx(request)
    settings = ctx.settings
    key = _stored_key(settings)
    if not key:
        raise HTTPException(status_code=400, detail="nessuna chiave OpenRouter impostata")

    key_check = check_key_valid(key, settings.llm_base_url)
    credits_check = check_key_credits(key, settings.llm_base_url)
    model_check = check_llm_model(key, settings.llm_model, settings.llm_base_url)

    checks = [key_check, credits_check, model_check]
    if any(c.status == Status.FAIL for c in checks):
        overall = Status.FAIL
    elif any(c.status == Status.WARN for c in checks):
        overall = Status.WARN
    else:
        overall = Status.OK

    def out(result: CheckResult) -> CheckOut:
        return CheckOut(
            id=result.id,
            status=result.status,
            code=result.code,
            message=result.message,
            fix=result.fix,
        )

    return VerifyKeyOut(
        status=overall,
        key_valid=out(key_check),
        credits=out(credits_check),
        model=out(model_check),
        model_name=settings.llm_model,
    )
