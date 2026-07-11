"""Multimodal ingestion business logic — the staged processing pipeline.

`create_or_get_job` enqueues a job for a document (skipping reprocessing of an unchanged file); a
background runner later calls `process_now`, which consumes the injected engine's events, persists
OCR (cached) + extracted images/tables/figures + multimodal chunks + logs, tracks per-stage
progress, and honors cancellation. The engine (not this service) touches OCR/vision libs — reused,
never forked. Text retrieval (Phase 1) is untouched: multimodal chunks land with
`embedding_status="pending"` (the future embedding queue).
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ingestion import validation
from app.ingestion.chunking import build_multimodal_chunks
from app.ingestion.errors import DocumentNotFound, IngestionStateError, JobNotFound
from app.ingestion.models import (
    ExtractedFigure,
    ExtractedImage,
    ExtractedTable,
    MultimodalChunk,
    OcrResult,
    ProcessingJob,
)
from app.ingestion.repository import IngestionRepository
from app.ingestion.storage import AssetStorage


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _file_hash(path: str) -> str:
    try:
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                h.update(block)
        return h.hexdigest()[:32]
    except Exception:
        return ""


class _OcrCacheView:
    """Read accessor the engine uses to skip re-OCR of already-recognized pages."""

    def __init__(self, repo: IngestionRepository, document_id: str):
        self._repo = repo
        self._document_id = document_id

    def get(self, page_number: int, content_hash: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get_ocr(self._document_id, page_number, content_hash)
        if row is None:
            return None
        return {"text": row.text, "confidence": row.confidence, "language": row.language, "boxes": row.boxes}


class IngestionService:
    def __init__(self, repo: IngestionRepository, workspace_id_getter=None):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ helpers
    def _document(self, document_id: str, owner_id: str, workspace_id: str):
        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise DocumentNotFound(document_id)
        return doc

    def _job_or_404(self, job_id: str, owner_id: str) -> ProcessingJob:
        job = self.repo.get_job(job_id, owner_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    # ------------------------------------------------------------------ create / enqueue
    def create_or_get_job(self, owner_id: str, workspace_id: str, document_id: str, *, force: bool = False) -> ProcessingJob:
        doc = self._document(document_id, owner_id, workspace_id)
        validation.validate_supported(doc.file_type or "")  # 415 on unsupported media
        file_hash = _file_hash(doc.storage_path) or doc.vector_document_id

        latest = self.repo.latest_job_for_document(document_id, owner_id)
        if latest is not None and not force:
            # Skip reprocessing an unchanged file that already completed (perf: no duplicate work).
            if latest.status == "completed" and latest.file_hash == file_hash:
                return latest
            # A non-terminal job for the same file → return it (already queued/processing).
            if latest.status in ("queued", "processing"):
                return latest

        job = ProcessingJob(
            workspace_id=workspace_id, owner_id=owner_id, document_id=document_id,
            file_hash=file_hash, status="queued", stage="queued", progress=0,
            page_count=doc.page_count,
        )
        return self.repo.create_job(job)

    # ------------------------------------------------------------------ the pipeline
    def process_now(self, job_id: str, engine, storage: Optional[AssetStorage] = None) -> Optional[ProcessingJob]:
        job = self.repo.get_job_by_id_only(job_id)
        if job is None:
            return None
        if job.status == "cancelled":
            return job
        storage = storage or AssetStorage()

        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(job.document_id, job.owner_id)
        if doc is None:
            job.status = "failed"; job.stage = "failed"; job.error = "Document was deleted."
            self.repo.save_job(job)
            return job

        started = time.perf_counter()
        self.repo.clear_job_assets(job.id, job.document_id)  # clean slate; OCR cache is preserved
        job.status = "processing"; job.stage = "validating"; job.progress = 1; job.error = None
        job.attempts += 1
        job.image_count = job.table_count = job.figure_count = job.chunk_count = job.ocr_pages = 0
        self.repo.save_job(job)
        self.repo.log(job, "pipeline", "Processing started.")

        cache = _OcrCacheView(self.repo, job.document_id)
        ocr_pages: List[Dict[str, Any]] = []
        images: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []
        figures: List[Dict[str, Any]] = []
        confidences: List[float] = []

        try:
            for ev in engine.process(job, doc, storage, cache):
                etype = ev.get("type")
                if etype == "classification":
                    job.doc_type = ev.get("doc_type", "unknown")
                    job.processing_type = ev.get("processing_type", "native")
                    job.ocr_language = ev.get("language", "") or ""
                    self.repo.save_job(job)
                    self.repo.log(job, "classification", f"Classified as {job.doc_type} ({job.processing_type}).")
                elif etype == "stage":
                    self.db.refresh(job)
                    if job.status == "cancelled":
                        job.stage = "cancelled"; self.repo.save_job(job)
                        self.repo.log(job, "pipeline", "Cancelled by user.", "warn")
                        return job
                    job.stage = ev.get("stage", job.stage)
                    job.progress = int(ev.get("progress", job.progress))
                    self.repo.save_job(job)
                elif etype == "ocr":
                    self._persist_ocr(job, ev, ocr_pages, confidences)
                elif etype == "image":
                    images.append(self._persist_image(job, doc, storage, ev))
                elif etype == "table":
                    tables.append(self._persist_table(job, ev))
                elif etype == "figure":
                    figures.append(self._persist_figure(job, doc, storage, ev))
                elif etype == "final":
                    job.pipeline_version = ev.get("pipeline_version", job.pipeline_version)

            # --- multimodal chunking + metadata finalization ---
            job.stage = "chunking"; job.progress = 90; self.repo.save_job(job)
            chunk_dicts = build_multimodal_chunks(ocr_pages=ocr_pages, images=images, tables=tables, figures=figures)
            rows = [MultimodalChunk(
                job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
                page_number=c["page_number"], chunk_type=c["chunk_type"], source=c["source"],
                chunk_index=c["chunk_index"], asset_id=c.get("asset_id"), bbox=c.get("bbox"),
                content=c["content"][:20000], meta=c.get("meta"), embedding_status="pending",
            ) for c in chunk_dicts]
            self.repo.add_chunks(rows)

            job.chunk_count = len(rows)
            job.ocr_pages = len(ocr_pages)
            job.image_count = len(images)
            job.table_count = len(tables)
            job.figure_count = len(figures)
            job.ocr_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
            job.processing_ms = int((time.perf_counter() - started) * 1000)
            job.status = "completed"; job.stage = "completed"; job.progress = 100
            self.repo.save_job(job)
            self.repo.log(job, "pipeline",
                          f"Completed: {job.image_count} images, {job.table_count} tables, "
                          f"{job.figure_count} figures, {job.chunk_count} chunks.")
            self._update_document(doc, job)
        except Exception as e:  # failure recovery — keep partial assets, record the error
            job.status = "failed"; job.stage = "failed"; job.error = str(e)[:4000]
            job.processing_ms = int((time.perf_counter() - started) * 1000)
            self.repo.save_job(job)
            self.repo.log(job, "pipeline", f"Failed: {e}", "error")
            return job
        return job

    # ------------------------------------------------------------------ persistence helpers
    def _persist_ocr(self, job, ev, ocr_pages, confidences) -> None:
        page_number = int(ev.get("page_number", 0))
        text = ev.get("text", "") or ""
        conf = ev.get("confidence")
        lang = ev.get("language", "") or ""
        if not ev.get("cached") and ev.get("from_ocr", True):
            content_hash = ev.get("content_hash", "")
            if self.repo.get_ocr(job.document_id, page_number, content_hash) is None:
                self.repo.add_ocr(OcrResult(
                    workspace_id=job.workspace_id, document_id=job.document_id, page_number=page_number,
                    content_hash=content_hash, text=text, confidence=conf, language=lang,
                    boxes=ev.get("boxes"), reading_order=ev.get("reading_order")))
        if conf is not None:
            confidences.append(float(conf))
        ocr_pages.append({"page_number": page_number, "text": text, "confidence": conf,
                          "language": lang, "from_ocr": bool(ev.get("from_ocr", True))})

    def _persist_image(self, job, doc, storage, ev) -> Dict[str, Any]:
        row = ExtractedImage(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            page_number=int(ev.get("page_number", 0)), bbox=ev.get("bbox"),
            width=int(ev.get("width", 0)), height=int(ev.get("height", 0)),
            image_type=ev.get("image_type", "raster"), confidence=ev.get("confidence"),
            hash=ev.get("hash", ""))
        self.repo.add_image(row)
        path = storage.write_asset(job.workspace_id, job.document_id, "images", row.id,
                                   ev.get("bytes", b""), ev.get("ext", "png"))
        row.storage_path = path
        self.db.commit()
        return {"page_number": row.page_number, "bbox": row.bbox, "image_type": row.image_type,
                "width": row.width, "height": row.height, "asset_id": row.id, "caption": None}

    def _persist_table(self, job, ev) -> Dict[str, Any]:
        rows = ev.get("rows", []) or []
        row = ExtractedTable(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            page_number=int(ev.get("page_number", 0)), bbox=ev.get("bbox"),
            n_rows=len(rows), n_cols=len(ev.get("headers", []) or (rows[0] if rows else [])),
            headers=ev.get("headers"), cells=rows, caption=ev.get("caption"))
        self.repo.add_table(row)
        return {"page_number": row.page_number, "bbox": row.bbox, "headers": row.headers,
                "cells": rows, "n_rows": row.n_rows, "n_cols": row.n_cols,
                "caption": row.caption, "asset_id": row.id}

    def _persist_figure(self, job, doc, storage, ev) -> Dict[str, Any]:
        row = ExtractedFigure(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            page_number=int(ev.get("page_number", 0)), bbox=ev.get("bbox"),
            figure_type=ev.get("figure_type", "figure"), caption=ev.get("caption"), hash=ev.get("hash", ""))
        self.repo.add_figure(row)
        if ev.get("bytes"):
            row.storage_path = storage.write_asset(job.workspace_id, job.document_id, "figures", row.id,
                                                   ev.get("bytes", b""), ev.get("ext", "png"))
            self.db.commit()
        return {"page_number": row.page_number, "bbox": row.bbox, "figure_type": row.figure_type,
                "caption": row.caption, "asset_id": row.id}

    def _update_document(self, doc, job) -> None:
        """Reflect multimodal processing on the Document row (does NOT alter text retrieval)."""
        from app.documents.repository import DocumentRepository
        any_ocr = job.ocr_pages > 0 and job.processing_type in ("ocr", "mixed", "image_only")
        doc.ocr_status = "completed" if any_ocr else "native"
        DocumentRepository(self.db).save(doc)

    # ------------------------------------------------------------------ commands
    def retry(self, job_id: str, owner_id: str) -> ProcessingJob:
        job = self._job_or_404(job_id, owner_id)
        if job.status not in ("failed", "cancelled"):
            raise IngestionStateError(f"Cannot retry a '{job.status}' job.")
        job.status = "queued"; job.stage = "queued"; job.progress = 0; job.error = None
        return self.repo.save_job(job)

    def cancel(self, job_id: str, owner_id: str) -> ProcessingJob:
        job = self._job_or_404(job_id, owner_id)
        if job.status not in ("queued", "processing"):
            raise IngestionStateError(f"Cannot cancel a '{job.status}' job.")
        job.status = "cancelled"; job.stage = "cancelled"
        return self.repo.save_job(job)

    # ------------------------------------------------------------------ queries
    def get(self, job_id: str, owner_id: str) -> ProcessingJob:
        return self._job_or_404(job_id, owner_id)

    def detail(self, job_id: str, owner_id: str):
        job = self._job_or_404(job_id, owner_id)
        return job, self.repo.logs_for(job.id)

    def status_for_document(self, document_id: str, owner_id: str, workspace_id: str) -> Optional[ProcessingJob]:
        self._document(document_id, owner_id, workspace_id)
        return self.repo.latest_job_for_document(document_id, owner_id)

    def assets(self, document_id: str, owner_id: str, workspace_id: str):
        self._document(document_id, owner_id, workspace_id)
        return (self.repo.images_for(document_id), self.repo.tables_for(document_id), self.repo.figures_for(document_id))

    def chunks(self, document_id: str, owner_id: str, workspace_id: str, chunk_type: Optional[str] = None):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.chunks_for(document_id, chunk_type)

    def ocr_status(self, document_id: str, owner_id: str, workspace_id: str):
        self._document(document_id, owner_id, workspace_id)
        rows = self.repo.ocr_for_document(document_id)
        confs = [r.confidence for r in rows if r.confidence is not None]
        return rows, (round(sum(confs) / len(confs), 4) if confs else None)
