"""Endpoint job: creazione, stato, log SSE, download, cancellazione."""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ... import audit
from ...auth import Actor, authorize, get_current_actor
from ...metrics import JOBS_SUBMITTED, METRICS
from ...models import (
    ENGINES,
    LANGUAGES,
    JobOut,
    JobRecord,
    JobRequest,
    JobState,
    JobSummary,
    RangeMode,
)
from ...pages import parse_pages
from ...quota import check_quota
from ...security import sanitize_stem
from ...sse import job_event_stream
from .deps import get_ctx

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ACTIVE = {JobState.queued, JobState.running}


def _download_url(job: JobRecord) -> str | None:
    if job.artifact_path and Path(job.artifact_path).is_file():
        return f"/api/v1/jobs/{job.job_id}/download"
    return None


def _job_out(ctx, job: JobRecord) -> JobOut:
    if job.state == JobState.queued:
        job.queue_position = ctx.queue_position(job.job_id)
    return job.to_out(download_url=_download_url(job))


@router.post("", response_model=JobOut, status_code=201)
def create_job(payload: JobRequest, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    settings = ctx.settings

    if not ctx.rate_limiter.allow(f"job:{actor.id}"):
        raise HTTPException(
            status_code=429,
            detail="troppe richieste",
            headers={"Retry-After": str(ctx.rate_limiter.retry_after(f"job:{actor.id}"))},
        )
    if ctx.queue.qsize() >= settings.max_queue_size:
        raise HTTPException(status_code=429, detail="coda piena, riprova più tardi")

    document = ctx.storage.get_document(payload.doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="documento non trovato")
    authorize(actor, document.owner_id)
    if payload.engine not in ENGINES:
        raise HTTPException(status_code=400, detail=f"motore sconosciuto: {payload.engine}")
    if payload.src_lang not in LANGUAGES:
        raise HTTPException(status_code=400, detail=f"lingua origine sconosciuta: {payload.src_lang}")
    if payload.dst_lang not in LANGUAGES or payload.dst_lang == "auto":
        raise HTTPException(status_code=400, detail=f"lingua destinazione sconosciuta: {payload.dst_lang}")
    try:
        pages = parse_pages(payload.pages, document.page_count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if len(pages) > settings.max_pages_per_job:
        raise HTTPException(
            status_code=413,
            detail=f"troppe pagine (max {settings.max_pages_per_job} per job)",
        )
    check_quota(actor, len(pages), settings, ctx.storage)

    default_name = f"{sanitize_stem(Path(document.filename).stem, 'document')}_{payload.dst_lang}"
    output_name = sanitize_stem(payload.output_name or default_name, default_name)

    job = JobRecord(
        job_id=uuid.uuid4().hex,
        doc_id=document.doc_id,
        pages=pages,
        src_lang=payload.src_lang,
        dst_lang=payload.dst_lang,
        engine=payload.engine,
        output_name=output_name,
        range_mode=payload.range_mode,
        state=JobState.queued,
        priority=max(0, min(int(payload.priority), 10)),
        pages_total=len(pages),
        owner_id=actor.id,
    )
    ctx.storage.create_job(job)
    try:
        ctx.queue.submit(job.job_id, job.priority)
    except RuntimeError as exc:
        ctx.storage.update_job(job.job_id, state=JobState.error, error=str(exc))
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    METRICS.inc(JOBS_SUBMITTED)
    audit.record(
        ctx.storage, actor, "job.create", job.job_id,
        {"pages": len(pages), "engine": job.engine},
    )
    job.queue_position = ctx.queue_position(job.job_id)
    return job.to_out(download_url=None)


@router.get("", response_model=list[JobSummary])
def list_jobs(request: Request, limit: int = 50, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    jobs = ctx.storage.list_jobs(limit=max(1, min(limit, 200)))
    return [
        JobSummary(
            job_id=j.job_id,
            doc_id=j.doc_id,
            state=j.state,
            engine=j.engine,
            dst_lang=j.dst_lang,
            output_name=j.output_name,
            pages_total=j.pages_total,
            pages_done=j.pages_done,
            created=j.created,
        )
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    job = ctx.storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job non trovato")
    authorize(actor, job.owner_id)
    return _job_out(ctx, job)


@router.get("/{job_id}/events")
def job_events(job_id: str, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    job = ctx.storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job non trovato")
    authorize(actor, job.owner_id)
    return StreamingResponse(
        job_event_stream(ctx.storage, job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{job_id}/download")
def download(job_id: str, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    job = ctx.storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job non trovato")
    authorize(actor, job.owner_id)
    if not job.artifact_path or not Path(job.artifact_path).is_file():
        raise HTTPException(status_code=409, detail="output non disponibile")
    suffix = Path(job.artifact_path).suffix
    filename = f"{job.output_name}{suffix}"
    audit.record(ctx.storage, actor, "job.download", job_id)
    return FileResponse(job.artifact_path, filename=filename)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    job = ctx.storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job non trovato")
    authorize(actor, job.owner_id)
    if job.state in {JobState.done, JobState.error, JobState.cancelled}:
        return _job_out(ctx, job)
    ctx.queue.cancel(job_id)
    audit.record(ctx.storage, actor, "job.cancel", job_id)
    job = ctx.storage.get_job(job_id) or job
    return _job_out(ctx, job)
