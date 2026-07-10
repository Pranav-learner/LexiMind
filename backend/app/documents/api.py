"""Document HTTP routes — thin transport adapters over DocumentService.

Every route is authenticated (`get_current_user_id`) and scoped to an owned workspace, so a
user can only ever see or mutate documents in their own workspaces. Domain errors are
translated to HTTP here; no business logic lives in this file.

Heavy retrieval singletons (FAISS/BM25) and the ingestion function are pulled in through
FastAPI dependencies that import them *lazily*. This keeps `app.documents.api` importable in
the light test environment (no faiss/torch at import time) and lets tests override those
dependencies with in-memory fakes to drive the full HTTP lifecycle.
"""

from __future__ import annotations

import os
import time
from math import ceil
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.core.config import settings
from app.db.base import get_db
from app.documents import indexing, validation
from app.documents.errors import DocumentError
from app.documents.repository import DocumentRepository
from app.documents.schemas import (
    ArchivedFilter,
    ChunkOut,
    DocumentChunksResponse,
    DocumentDetail,
    DocumentListResponse,
    DocumentOut,
    DocumentUpdate,
    IndexedFilter,
    SortField,
    SortOrder,
    UploadItemResult,
    UploadResponse,
)
from app.documents.service import DocumentService
from app.retrieval.schemas import derive_document_id
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["documents"])


# ----------------------------------------------------------------- dependencies
def get_index_context():
    """Return the (vector_store, bm25_retriever) singletons. Overridden in tests.

    Imported lazily so the light test env never loads faiss/torch just to import this module.
    """
    from app.core.state import bm25_retriever, vector_store

    return vector_store, bm25_retriever


def get_ingestor():
    """Return the ingestion callable. Overridden in tests with a fast fake."""
    from app.services.ingestion_service import ingest_pdf

    return ingest_pdf


# ----------------------------------------------------------------- helpers
def _service(db: Session) -> DocumentService:
    return DocumentService(DocumentRepository(db), WorkspaceService(WorkspaceRepository(db)))


def _handle(fn):
    try:
        return fn()
    except DocumentError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    """404 unless the workspace exists and belongs to the caller."""
    ws = WorkspaceRepository(db).get(workspace_id, owner_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _out(doc) -> DocumentOut:
    return DocumentOut.model_validate(doc)


# ----------------------------------------------------------------- upload (single + multi)
@router.post("", response_model=UploadResponse, status_code=201)
async def upload_documents(
    workspace_id: str,
    files: List[UploadFile] = File(...),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    index_ctx=Depends(get_index_context),
    ingest=Depends(get_ingestor),
):
    """Upload one or many files into a workspace and process each into indexed chunks.

    Each file is handled independently: a validation/duplicate/processing failure on one file
    is reported in its `items` entry without aborting the rest of the batch.
    """
    _verify_workspace(db, workspace_id, owner_id)
    vector_store, bm25 = index_ctx
    service = _service(db)

    results: List[UploadItemResult] = []
    for upload in files:
        original = upload.filename or "untitled"
        try:
            item = await _process_one_upload(
                service, vector_store, bm25, ingest, workspace_id, owner_id, upload
            )
            results.append(item)
        except DocumentError as e:
            results.append(UploadItemResult(filename=original, success=False, error=str(e)))
        except Exception as e:  # pragma: no cover - defensive; keep the batch alive
            results.append(UploadItemResult(filename=original, success=False, error=str(e)))

    uploaded = sum(1 for r in results if r.success)
    return UploadResponse(uploaded=uploaded, failed=len(results) - uploaded, items=results)


async def _process_one_upload(
    service: DocumentService,
    vector_store,
    bm25,
    ingest,
    workspace_id: str,
    owner_id: str,
    upload: UploadFile,
) -> UploadItemResult:
    safe_name = validation.sanitize_filename(upload.filename or "untitled")
    ext = validation.validate_file_type(safe_name)          # 415 on unsupported type
    data = await upload.read()
    validation.validate_file_size(len(data))                # 413 on oversize / empty

    vector_document_id = derive_document_id(safe_name)
    # Row first: duplicate/validation errors reject the upload before any disk/embed work.
    doc = service.create_pending(
        owner_id,
        workspace_id,
        filename=safe_name,
        vector_document_id=vector_document_id,
        storage_path="",
        file_type=ext,
        mime_type=validation.mime_for(ext),
        file_size=len(data),
    )

    # Persist bytes under a per-document, workspace-namespaced path (no cross-file overwrite).
    dest_dir = os.path.join(settings.upload_dir, workspace_id)
    os.makedirs(dest_dir, exist_ok=True)
    storage_path = os.path.join(dest_dir, f"{doc.id}__{safe_name}")
    with open(storage_path, "wb") as f:
        f.write(data)
    doc.storage_path = storage_path
    service.set_stage(doc, "uploaded")

    try:
        started = time.perf_counter()
        result = ingest(
            storage_path,
            safe_name,
            vector_store,
            bm25,
            workspace_id=workspace_id,
            on_stage=lambda stage: service.set_stage(doc, stage),
            replace_existing=True,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        service.complete(
            doc,
            page_count=int(result.get("pages_extracted", 0)),
            word_count=int(result.get("word_count", 0)),
            chunk_count=int(result.get("total_chunks", 0)),
            language=validation.guess_language(result.get("sample_text", "")),
            embedding_model=result.get("embedding_model", settings.embedding_model),
            embedding_dimension=int(result.get("embedding_dimension", settings.embedding_dim)),
            processing_ms=elapsed_ms,
            count_as_new=True,
        )
    except Exception as e:
        service.fail(doc, str(e))
        return UploadItemResult(filename=safe_name, success=False, error=str(e), document=_out(doc))

    return UploadItemResult(filename=safe_name, success=True, document=_out(doc))


# ----------------------------------------------------------------- list
@router.get("", response_model=DocumentListResponse)
def list_documents(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    archived: ArchivedFilter = Query(ArchivedFilter.active),
    indexed: IndexedFilter = Query(IndexedFilter.any),
    file_type: str | None = Query(None),
    language: str | None = Query(None),
    sort_by: SortField = Query(SortField.created_at),
    order: SortOrder = Query(SortOrder.desc),
):
    _verify_workspace(db, workspace_id, owner_id)
    items, total = _service(db).list(
        owner_id,
        workspace_id,
        page=page,
        page_size=page_size,
        search=search,
        archived=archived,
        indexed=indexed,
        file_type=file_type,
        language=language,
        sort_by=sort_by,
        order=order,
    )
    return DocumentListResponse(
        items=[_out(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if page_size else 0,
    )


# ----------------------------------------------------------------- details (with index health)
@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    workspace_id: str,
    document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    index_ctx=Depends(get_index_context),
):
    _verify_workspace(db, workspace_id, owner_id)
    doc = _handle(lambda: _service(db).get(document_id, owner_id))
    detail = DocumentDetail.model_validate(doc)
    try:
        vector_store, bm25 = index_ctx
        detail.index_health = indexing.compute_index_health(vector_store, bm25, doc)
    except Exception:
        detail.index_health = None  # index layer unavailable — still return the row
    return detail


# ----------------------------------------------------------------- viewer: resolve citation
@router.get("/by-vector/{vector_document_id}", response_model=DocumentOut)
def resolve_document_by_vector(
    workspace_id: str,
    vector_document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Map an AI citation's `document_id` (the vector id) to its Document row.

    Lets the frontend jump from a `[Source: OS.pdf Page 142]` citation straight into the
    viewer. 404 if the workspace isn't owned or no live document matches.
    """
    _verify_workspace(db, workspace_id, owner_id)
    doc = _service(db).get_by_vector_id(workspace_id, vector_document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="No document matches that citation.")
    return _out(doc)


# ----------------------------------------------------------------- viewer: raw PDF bytes
@router.get("/{document_id}/file")
def get_document_file(
    workspace_id: str,
    document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Stream the stored file so PDF.js can render it. Auth + owner scoped."""
    _verify_workspace(db, workspace_id, owner_id)
    doc = _handle(lambda: _service(db).get(document_id, owner_id))
    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="Source file is unavailable.")
    return FileResponse(
        doc.storage_path,
        media_type=doc.mime_type or "application/pdf",
        filename=doc.filename,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


# ----------------------------------------------------------------- viewer: chunks (per page)
@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
def get_document_chunks(
    workspace_id: str,
    document_id: str,
    page: int | None = Query(None, ge=1, description="Restrict to a single 1-based page."),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    index_ctx=Depends(get_index_context),
):
    """Return a document's indexed chunks (page, section, text) for citation highlighting,
    the section outline, and per-page text lookup."""
    _verify_workspace(db, workspace_id, owner_id)
    doc = _handle(lambda: _service(db).get(document_id, owner_id))
    vector_store, _ = index_ctx
    records = indexing.list_document_chunks(
        vector_store, doc.vector_document_id, doc.workspace_id, page=page
    )
    items = [
        ChunkOut(
            chunk_id=m.get("chunk_id") or f"{doc.vector_document_id}:{m.get('chunk_index')}",
            document_id=m.get("document_id"),
            page_number=m.get("page_number"),
            section=m.get("section") or m.get("section_heading"),
            chunk_index=m.get("chunk_index"),
            text=m.get("text", ""),
        )
        for m in records
    ]
    return DocumentChunksResponse(
        document_id=doc.id,
        vector_document_id=doc.vector_document_id,
        total=len(items),
        items=items,
    )


# ----------------------------------------------------------------- rename / edit
@router.patch("/{document_id}", response_model=DocumentOut)
def update_document(
    workspace_id: str,
    document_id: str,
    req: DocumentUpdate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    doc = _handle(
        lambda: _service(db).update(
            document_id, owner_id, display_name=req.display_name, description=req.description
        )
    )
    return _out(doc)


# ----------------------------------------------------------------- archive / restore
@router.post("/{document_id}/archive", response_model=DocumentOut)
def archive_document(
    workspace_id: str,
    document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    doc = _handle(lambda: _service(db).archive(document_id, owner_id))
    return _out(doc)


@router.post("/{document_id}/restore", response_model=DocumentOut)
def restore_document(
    workspace_id: str,
    document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    doc = _handle(lambda: _service(db).restore(document_id, owner_id))
    return _out(doc)


# ----------------------------------------------------------------- re-index
@router.post("/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(
    workspace_id: str,
    document_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    index_ctx=Depends(get_index_context),
    ingest=Depends(get_ingestor),
):
    _verify_workspace(db, workspace_id, owner_id)
    service = _service(db)
    doc = _handle(lambda: service.get(document_id, owner_id))

    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=409, detail="Source file is unavailable; cannot re-index.")

    vector_store, bm25 = index_ctx
    service.mark_stale(doc)
    try:
        started = time.perf_counter()
        result = ingest(
            doc.storage_path,
            doc.filename,
            vector_store,
            bm25,
            workspace_id=doc.workspace_id,
            on_stage=lambda stage: service.set_stage(doc, stage),
            replace_existing=True,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        service.complete(
            doc,
            page_count=int(result.get("pages_extracted", 0)),
            word_count=int(result.get("word_count", 0)),
            chunk_count=int(result.get("total_chunks", 0)),
            language=validation.guess_language(result.get("sample_text", "")),
            embedding_model=result.get("embedding_model", settings.embedding_model),
            embedding_dimension=int(result.get("embedding_dimension", settings.embedding_dim)),
            processing_ms=elapsed_ms,
            count_as_new=False,  # already counted at first upload
        )
    except Exception as e:
        service.fail(doc, str(e))
        raise HTTPException(status_code=500, detail=f"Re-index failed: {e}")
    return _out(doc)


# ----------------------------------------------------------------- delete (soft / permanent)
@router.delete("/{document_id}", status_code=204)
def delete_document(
    workspace_id: str,
    document_id: str,
    permanent: bool = Query(False, description="Hard-delete + purge chunks instead of soft-delete."),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    index_ctx=Depends(get_index_context),
):
    _verify_workspace(db, workspace_id, owner_id)
    service = _service(db)

    if permanent:
        # Load first so we can purge chunks + the physical file, then hard-delete the row.
        doc = _handle(lambda: service.get(document_id, owner_id))
        try:
            vector_store, bm25 = index_ctx
            indexing.remove_document_chunks(
                vector_store, bm25, doc.vector_document_id, doc.workspace_id
            )
        except Exception:
            pass  # index cleanup best-effort; the row is still removed
        if doc.storage_path and os.path.exists(doc.storage_path):
            try:
                os.remove(doc.storage_path)
            except OSError:
                pass

    _handle(lambda: service.delete(document_id, owner_id, permanent=permanent))
    return None
