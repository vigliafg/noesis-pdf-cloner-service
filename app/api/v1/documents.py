"""Endpoint documenti: upload, metadati, anteprima (thumbnail), delete."""

from __future__ import annotations

import contextlib
import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from ... import audit
from ...auth import Actor, authorize, get_current_actor
from ...engine import CloneEngine
from ...models import DocumentOut, DocumentRecord, PageRef, utcnow
from ...security import validate_pdf_upload
from .deps import get_ctx

router = APIRouter(prefix="/documents", tags=["documents"])


def _document_out(doc: DocumentRecord) -> DocumentOut:
    labels = doc.page_labels or [str(i + 1) for i in range(doc.page_count)]
    if len(labels) != doc.page_count:
        labels = [str(i + 1) for i in range(doc.page_count)]
    pages = [
        PageRef(index=i, number=i + 1, label=labels[i])
        for i in range(doc.page_count)
    ]
    return DocumentOut(
        doc_id=doc.doc_id,
        filename=doc.filename,
        page_count=doc.page_count,
        size_bytes=doc.size_bytes,
        page_labels=labels,
        pages=pages,
        created=doc.created,
    )


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    actor: Actor = Depends(get_current_actor),
):
    """Carica un PDF e ne estrae i metadati (pagine + etichette /PageLabels)."""
    ctx = get_ctx(request)
    settings = ctx.settings
    if not ctx.rate_limiter.allow(f"upload:{actor.id}"):
        raise HTTPException(
            status_code=429,
            detail="troppe richieste",
            headers={"Retry-After": str(ctx.rate_limiter.retry_after(f"upload:{actor.id}"))},
        )
    try:
        validate_pdf_upload(file.filename, 1, settings.max_upload_mb)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_id = uuid.uuid4().hex
    dest = ctx.storage.document_path(doc_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    hasher = hashlib.sha256()
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if max_bytes and size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"file troppo grande (max {settings.max_upload_mb} MB)",
                    )
                hasher.update(chunk)
                out.write(chunk)
        validate_pdf_upload(file.filename, size, settings.max_upload_mb)
        page_count = CloneEngine.page_count(dest)
        labels = CloneEngine.page_labels(dest)
        toc = CloneEngine.toc(dest)
    except HTTPException:
        _cleanup(dest)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(dest)
        raise HTTPException(status_code=400, detail=f"PDF non valido: {exc}") from exc

    document = DocumentRecord(
        doc_id=doc_id,
        filename=file.filename or "document.pdf",
        sha256=hasher.hexdigest(),
        page_count=page_count,
        path=str(dest),
        page_labels=labels,
        toc=toc,
        owner_id=actor.id,
        size_bytes=size,
        created=utcnow(),
        updated=utcnow(),
    )
    ctx.storage.create_document(document)
    audit.record(ctx.storage, actor, "document.upload", doc_id, {"pages": page_count})
    return _document_out(document)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    document = ctx.storage.get_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="documento non trovato")
    authorize(actor, document.owner_id)
    return _document_out(document)


@router.get("/{doc_id}/thumb")
def get_thumbnail(
    doc_id: str,
    request: Request,
    page: int = 0,
    w: int = 200,
    actor: Actor = Depends(get_current_actor),
) -> Response:
    """Miniatura PNG (0-based ``page``, larghezza ``w``), cachata su disco."""
    ctx = get_ctx(request)
    document = ctx.storage.get_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="documento non trovato")
    authorize(actor, document.owner_id)
    if page < 0 or page >= document.page_count:
        raise HTTPException(status_code=400, detail="pagina fuori intervallo")
    width = max(40, min(int(w), 800))
    thumb = ctx.storage.thumb_path(document.sha256, page)
    if not thumb.is_file():
        try:
            data = CloneEngine.render_thumb(document.path, page, width=width)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"anteprima non disponibile: {exc}") from exc
        thumb.parent.mkdir(parents=True, exist_ok=True)
        tmp = thumb.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, thumb)
    return Response(
        content=thumb.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, request: Request, actor: Actor = Depends(get_current_actor)):
    ctx = get_ctx(request)
    document = ctx.storage.get_document(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="documento non trovato")
    authorize(actor, document.owner_id)
    import shutil

    with contextlib.suppress(OSError):
        ctx.storage.document_path(doc_id).unlink()
    shutil.rmtree(ctx.storage.thumb_dir(document.sha256), ignore_errors=True)
    ctx.storage.delete_document(doc_id)
    audit.record(ctx.storage, actor, "document.delete", doc_id)
    return Response(status_code=204)


def _cleanup(path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()
