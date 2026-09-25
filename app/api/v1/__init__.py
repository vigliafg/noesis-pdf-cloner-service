"""Router API v1."""

from __future__ import annotations

from fastapi import APIRouter

from . import documents, jobs, llm, meta, ops

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(documents.router)
api_router.include_router(jobs.router)
api_router.include_router(llm.router)
api_router.include_router(meta.router)
api_router.include_router(ops.router)

__all__ = ["api_router"]
