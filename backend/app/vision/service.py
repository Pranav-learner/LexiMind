"""Vision Intelligence business logic — the async vision-understanding pipeline.

`create_or_get_job` enqueues a job over a document's Module-1 extracted assets; a background runner
later calls `process_now`, which consumes the injected vision engine's events, persists a
`VisionAnalysis` + `VisionEmbedding` per asset, WRITES THE CAPTION BACK to the Module-1 asset row
(the `caption` column reserved for exactly this), and enriches the asset's `MultimodalChunk` with the
caption + vision metadata (still `embedding_status="pending"` — retrieval untouched). The engine (not
this service) touches CLIP/BLIP — reused, never forked.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.vision.errors import DocumentNotFound, JobNotFound, VisionStateError
from app.vision.models import VisionAnalysis, VisionEmbedding, VisionJob


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VisionService:
    def __init__(self, repo, workspace_service=None):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ helpers
    def _document(self, document_id: str, owner_id: str, workspace_id: str):
        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise DocumentNotFound(document_id)
        return doc

    def _job_or_404(self, job_id: str, owner_id: str) -> VisionJob:
        job = self.repo.get_job(job_id, owner_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def _collect_assets(self, document_id: str) -> List[Dict[str, Any]]:
        """Gather the Module-1 extracted visual assets to understand (images + figures + tables)."""
        from app.ingestion.repository import IngestionRepository
        ing = IngestionRepository(self.db)
        assets: List[Dict[str, Any]] = []
        for im in ing.images_for(document_id):
            assets.append({"asset_type": "image", "asset_id": im.id, "page_number": im.page_number,
                           "image_type": im.image_type, "storage_path": im.storage_path, "caption": im.caption})
        for fg in ing.figures_for(document_id):
            assets.append({"asset_type": "figure", "asset_id": fg.id, "page_number": fg.page_number,
                           "figure_type": fg.figure_type, "storage_path": fg.storage_path, "caption": fg.caption})
        for tb in ing.tables_for(document_id):
            assets.append({"asset_type": "table", "asset_id": tb.id, "page_number": tb.page_number,
                           "headers": tb.headers, "cells": tb.cells, "caption": tb.caption})
        return assets

    # ------------------------------------------------------------------ create / enqueue
    def create_or_get_job(self, owner_id: str, workspace_id: str, document_id: str, *, force: bool = False) -> VisionJob:
        self._document(document_id, owner_id, workspace_id)
        latest = self.repo.latest_job_for_document(document_id, owner_id)
        if latest is not None and not force:
            if latest.status == "completed":
                return latest
            if latest.status in ("queued", "processing"):
                return latest
        assets = self._collect_assets(document_id)
        job = VisionJob(workspace_id=workspace_id, owner_id=owner_id, document_id=document_id,
                        status="queued", stage="queued", progress=0, asset_count=len(assets))
        return self.repo.create_job(job)

    # ------------------------------------------------------------------ the pipeline
    def process_now(self, job_id: str, engine, storage=None) -> Optional[VisionJob]:
        job = self.repo.get_job_by_id_only(job_id)
        if job is None:
            return None
        if job.status == "cancelled":
            return job
        if storage is None:
            from app.ingestion.storage import AssetStorage
            storage = AssetStorage()

        started = time.perf_counter()
        self.repo.clear_job(job.id)
        job.status = "processing"; job.stage = "loading"; job.progress = 1; job.error = None
        job.attempts += 1; job.analyzed_count = 0; job.embedding_count = 0
        logs: List[dict] = [{"stage": "pipeline", "level": "info", "message": "Vision analysis started."}]
        self.repo.save_job(job)

        assets = self._collect_assets(job.document_id)
        job.asset_count = len(assets)
        self.repo.save_job(job)
        if not assets:
            job.status = "completed"; job.stage = "completed"; job.progress = 100
            job.processing_ms = int((time.perf_counter() - started) * 1000)
            logs.append({"stage": "pipeline", "level": "info", "message": "No visual assets to analyze."})
            job.logs = logs
            self.repo.save_job(job)
            return job

        pending_analysis: Dict[str, VisionAnalysis] = {}  # asset_id -> row (to link embeddings)
        analyzed = embedded = 0  # local counters — set on the job at the end (a `refresh` in the
        # stage/cancellation check would otherwise clobber per-event increments before they commit).
        try:
            for ev in engine.process(job, assets, storage):
                etype = ev.get("type")
                if etype == "stage":
                    # Cancellation check reads ONLY the status column (never clobbers in-flight state).
                    from sqlalchemy import select
                    from app.vision.models import VisionJob as _VJ
                    if self.db.scalar(select(_VJ.status).where(_VJ.id == job.id)) == "cancelled":
                        job.status = "cancelled"; job.stage = "cancelled"; job.logs = logs; self.repo.save_job(job)
                        return job
                    job.stage = ev.get("stage", job.stage)
                    job.progress = int(ev.get("progress", job.progress))
                    job.analyzed_count = analyzed; job.embedding_count = embedded
                    self.repo.save_job(job)
                elif etype == "analysis":
                    row = self._persist_analysis(job, ev, storage)
                    pending_analysis[f"{ev['asset_type']}:{ev['asset_id']}"] = row
                    analyzed += 1
                    self._writeback_caption(ev)
                    self._enrich_chunk(job, ev)
                elif etype == "embedding":
                    key = f"{ev['asset_type']}:{ev['asset_id']}"
                    analysis = pending_analysis.get(key)
                    if analysis is not None:
                        self._persist_embedding(job, ev, analysis)
                        embedded += 1
                elif etype == "final":
                    job.model_name = ev.get("model_name", "")
                    job.embedding_model = ev.get("embedding_model", "")

            job.analyzed_count = analyzed; job.embedding_count = embedded
            job.status = "completed"; job.stage = "completed"; job.progress = 100
            job.processing_ms = int((time.perf_counter() - started) * 1000)
            logs.append({"stage": "pipeline", "level": "info",
                         "message": f"Analyzed {job.analyzed_count} assets, {job.embedding_count} embeddings."})
            job.logs = logs
            self.repo.save_job(job)
        except Exception as e:
            job.status = "failed"; job.stage = "failed"; job.error = str(e)[:4000]
            job.processing_ms = int((time.perf_counter() - started) * 1000)
            logs.append({"stage": "pipeline", "level": "error", "message": f"Failed: {e}"})
            job.logs = logs
            self.repo.save_job(job)
            return job
        return job

    # ------------------------------------------------------------------ persistence helpers
    def _persist_analysis(self, job, ev, storage) -> VisionAnalysis:
        thumb_path = ""
        if ev.get("thumbnail"):
            thumb_path = storage.write_asset(job.workspace_id, job.document_id, "thumbnails",
                                             f"{ev['asset_id']}", ev["thumbnail"], "png")
        row = VisionAnalysis(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            asset_type=ev["asset_type"], asset_id=ev["asset_id"], page_number=ev.get("page_number", 0),
            image_type=ev.get("image_type", "general_image"), caption=(ev.get("caption") or "")[:8000],
            objects=ev.get("objects"), relationships=ev.get("relationships"), structured=ev.get("structured"),
            keywords=ev.get("keywords"), topics=ev.get("topics"), complexity=ev.get("complexity", "low"),
            confidence=ev.get("confidence"), language=ev.get("language", ""), thumbnail_path=thumb_path,
            model_name=job.model_name or "")
        return self.repo.upsert_analysis(row)

    def _persist_embedding(self, job, ev, analysis: VisionAnalysis) -> None:
        self.repo.add_embedding(VisionEmbedding(
            analysis_id=analysis.id, workspace_id=job.workspace_id, document_id=job.document_id,
            asset_type=ev["asset_type"], asset_id=ev["asset_id"], model=ev.get("model", ""),
            model_family=ev.get("model_family", "fake"), dim=int(ev.get("dim", 0)), vector=ev.get("vector")))

    def _writeback_caption(self, ev) -> None:
        """Write the semantic caption back onto the Module-1 asset row (it reserved a `caption` column)."""
        from app.ingestion.models import ExtractedFigure, ExtractedImage, ExtractedTable
        model = {"image": ExtractedImage, "figure": ExtractedFigure, "table": ExtractedTable}.get(ev["asset_type"])
        if model is None:
            return
        row = self.db.get(model, ev["asset_id"])
        if row is not None:
            row.caption = (ev.get("caption") or "")[:4000]
            self.db.commit()

    def _enrich_chunk(self, job, ev) -> None:
        """Enrich the asset's MultimodalChunk with the caption + vision metadata (still pending)."""
        from sqlalchemy import select
        from app.ingestion.models import MultimodalChunk
        chunk = self.db.scalar(select(MultimodalChunk).where(
            MultimodalChunk.document_id == job.document_id, MultimodalChunk.asset_id == ev["asset_id"]))
        if chunk is None:
            return
        caption = (ev.get("caption") or "").strip()
        if caption:
            chunk.content = caption[:20000]
        meta = dict(chunk.meta or {})
        meta.update({"vision_image_type": ev.get("image_type"), "vision_confidence": ev.get("confidence"),
                     "vision_keywords": ev.get("keywords"), "vision_analyzed": True})
        chunk.meta = meta
        chunk.embedding_model = job.embedding_model or "pending"
        self.db.commit()

    # ------------------------------------------------------------------ commands
    def retry(self, job_id: str, owner_id: str) -> VisionJob:
        job = self._job_or_404(job_id, owner_id)
        if job.status not in ("failed", "cancelled"):
            raise VisionStateError(f"Cannot retry a '{job.status}' job.")
        job.status = "queued"; job.stage = "queued"; job.progress = 0; job.error = None
        return self.repo.save_job(job)

    def cancel(self, job_id: str, owner_id: str) -> VisionJob:
        job = self._job_or_404(job_id, owner_id)
        if job.status not in ("queued", "processing"):
            raise VisionStateError(f"Cannot cancel a '{job.status}' job.")
        job.status = "cancelled"; job.stage = "cancelled"
        return self.repo.save_job(job)

    # ------------------------------------------------------------------ queries
    def get(self, job_id: str, owner_id: str) -> VisionJob:
        return self._job_or_404(job_id, owner_id)

    def status_for_document(self, document_id: str, owner_id: str, workspace_id: str) -> Optional[VisionJob]:
        self._document(document_id, owner_id, workspace_id)
        return self.repo.latest_job_for_document(document_id, owner_id)

    def analyses(self, document_id: str, owner_id: str, workspace_id: str, image_type: Optional[str] = None):
        self._document(document_id, owner_id, workspace_id)
        rows = self.repo.analyses_for_document(document_id, image_type)
        return [(r, self.repo.has_embedding(r.id)) for r in rows]

    def analysis(self, analysis_id: str, owner_id: str, workspace_id: str):
        row = self.repo.get_analysis(analysis_id, workspace_id)
        if row is None:
            from app.vision.errors import AnalysisNotFound
            raise AnalysisNotFound(analysis_id)
        return row, self.repo.embedding_for_analysis(row.id)

    def search_meta(self, workspace_id: str, **kw):
        return self.repo.search_meta(workspace_id, **kw)
