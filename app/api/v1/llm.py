"""Validazione della chiave OpenRouter e del modello (BYOK).

Esegue gli stessi controlli della diagnostica (`app/diagnostics.py`) su una
chiave fornita dall'utente: validità della chiave, credito residuo, disponibilità
del modello. Non salva né registra la chiave.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...diagnostics import (
    CheckResult,
    Status,
    check_key_credits,
    check_key_valid,
    check_llm_model,
)

router = APIRouter(prefix="/llm", tags=["llm"])


class LlmValidateRequest(BaseModel):
    api_key: str = Field(min_length=1)
    model: str | None = None


class CheckOut(BaseModel):
    id: str
    status: str
    code: str = "ok"
    message: str = ""
    fix: str = ""


class LlmValidateOut(BaseModel):
    status: str  # ok | warn | fail
    key_valid: CheckOut
    credits: CheckOut
    model: CheckOut
    model_name: str


def _out(result: CheckResult) -> CheckOut:
    return CheckOut(
        id=result.id,
        status=result.status,
        code=result.code,
        message=result.message,
        fix=result.fix,
    )


def _overall(checks: list[CheckResult]) -> str:
    if any(c.status == Status.FAIL for c in checks):
        return Status.FAIL
    if any(c.status == Status.WARN for c in checks):
        return Status.WARN
    return Status.OK


@router.post("/validate", response_model=LlmValidateOut)
def validate_llm(payload: LlmValidateRequest, request: Request) -> LlmValidateOut:
    """Verifica chiave + credito + modello su OpenRouter (nessuna persistenza)."""
    settings = request.app.state.ctx.settings
    key = payload.api_key.strip()
    model = (payload.model or settings.llm_model).strip()

    key_check = check_key_valid(key)
    credits_check = check_key_credits(key)
    model_check = check_llm_model(key, model)

    checks = [key_check, credits_check, model_check]
    return LlmValidateOut(
        status=_overall(checks),
        key_valid=_out(key_check),
        credits=_out(credits_check),
        model=_out(model_check),
        model_name=model,
    )
