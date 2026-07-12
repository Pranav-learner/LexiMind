"""Media business logic — the staged temporal-processing pipeline.

`upload` creates the durable `Document` (media_type=audio|video) + persists bytes + enqueues a
`MediaJob`. A background runner later calls `process_now`, which consumes the injected engine's event
stream and persists: transcript segments, speakers + conversation turns, scenes, frames (+cached
frame-OCR), subtitles, unified temporal chunks, per-stage latencies, and logs — tracking progress and
honoring cancellation. The engine (not this service) touches ffmpeg/whisper/etc.; the OCR backend is
reused from Phase 4. Retrieval (Phase 1) is untouched — chunks land with `embedding_status="pending"`.

Cross-references (segment→speaker, frame→scene, scene→representative frame) are resolved in a single
finalization pass over buffered events (frames' bytes are written to storage as they stream, so only
lightweight metadata is buffered).
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.media import validation
from app.media.chunking import build_media_chunks
from app.media.errors import MediaNotFound, MediaJobNotFound, MediaStateError
from app.media.metadata import build_metadata
from app.media.models import (
    MediaChunk,
    MediaFrame,
    MediaJob,
    Scene,
    Speaker,
    SpeakerTurn,
    Subtitle,
    TranscriptSegment,
)
from app.media.repository import MediaRepository
from app.media.storage import MediaStorage


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
    """Read accessor the engine uses to skip re-OCR of an already-recognized frame.

    Reuses the Phase-4 OcrResult cache (keyed by document + page + content hash); for frames the
    engine passes frame_index as the page number.
    """

    def __init__(self, db, document_id: str):
        from app.ingestion.repository import IngestionRepository
        self._repo = IngestionRepository(db)
        self._document_id = document_id

    def get(self, page_number: int, content_hash: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get_ocr(self._document_id, page_number, content_hash)
        if row is None:
            return None
        return {"text": row.text, "confidence": row.confidence, "language": row.language, "boxes": row.boxes}


class MediaService:
    def __init__(self, repo: MediaRepository):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ helpers
    def _document(self, document_id: str, owner_id: str, workspace_id: str):
        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise MediaNotFound(document_id)
        return doc

    def _job_or_404(self, job_id: str, owner_id: str) -> MediaJob:
        job = self.repo.get_job(job_id, owner_id)
        if job is None:
            raise MediaJobNotFound(job_id)
        return job

    # ------------------------------------------------------------------ upload + enqueue
    def upload(self, owner_id: str, workspace_id: str, *, filename: str, data: bytes,
               storage_dir_factory) -> MediaJob:
        """Validate, persist the file as a Document(media_type), and enqueue a MediaJob.

        `storage_dir_factory(workspace_id) -> dir` lets the API decide where bytes land (prod upload
        dir vs. test temp dir) without this service importing FastAPI/config paths directly.
        """
        import os
        from app.documents.repository import DocumentRepository
        from app.documents.service import DocumentService
        from app.documents.validation import sanitize_filename
        from app.retrieval.schemas import derive_document_id
        from app.workspaces.repository import WorkspaceRepository
        from app.workspaces.service import WorkspaceService

        safe_name = sanitize_filename(filename or "untitled")
        ext = validation.validate_supported(validation.normalize_ext(safe_name))  # 415
        validation.validate_size(len(data))                                        # 413 / 422
        kind = validation.media_kind(ext)

        doc_service = DocumentService(DocumentRepository(self.db),
                                      WorkspaceService(WorkspaceRepository(self.db)))
        vector_document_id = derive_document_id(safe_name)
        doc = doc_service.create_pending(
            owner_id, workspace_id, filename=safe_name, vector_document_id=vector_document_id,
            storage_path="", file_type=ext, mime_type=validation.mime_for(ext), file_size=len(data),
            media_type=kind,  # Document.media_type is a free-form column designed for audio/video.
        )
        doc.processing_status = "uploaded"
        doc.processing_stage = "uploaded"
        doc.upload_progress = 100

        dest_dir = storage_dir_factory(workspace_id)
        os.makedirs(dest_dir, exist_ok=True)
        storage_path = os.path.join(dest_dir, f"{doc.id}__{safe_name}")
        with open(storage_path, "wb") as f:
            f.write(data)
        doc.storage_path = storage_path
        DocumentRepository(self.db).save(doc)

        return self.create_or_get_job(owner_id, workspace_id, doc.id, force=False)

    def create_or_get_job(self, owner_id: str, workspace_id: str, document_id: str, *,
                          force: bool = False) -> MediaJob:
        doc = self._document(document_id, owner_id, workspace_id)
        validation.validate_supported(doc.file_type or "")
        file_hash = _file_hash(doc.storage_path) or doc.vector_document_id

        latest = self.repo.latest_job_for_document(document_id, owner_id)
        if latest is not None and not force:
            if latest.status == "completed" and latest.file_hash == file_hash:
                return latest  # unchanged file already processed — never retranscribe (Step 4)
            if latest.status in ("queued", "processing"):
                return latest

        job = MediaJob(
            workspace_id=workspace_id, owner_id=owner_id, document_id=document_id,
            file_hash=file_hash, status="queued", stage="queued", progress=0,
            media_kind=doc.media_type if doc.media_type in ("audio", "video") else validation.media_kind(doc.file_type or ""),
        )
        return self.repo.create_job(job)

    # ------------------------------------------------------------------ the pipeline
    def process_now(self, job_id: str, engine, storage: Optional[MediaStorage] = None) -> Optional[MediaJob]:
        job = self.repo.get_job_by_id_only(job_id)
        if job is None:
            return None
        if job.status == "cancelled":
            return job
        storage = storage or MediaStorage()

        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(job.document_id, job.owner_id)
        if doc is None:
            job.status = "failed"; job.stage = "failed"; job.error = "Media document was deleted."
            self.repo.save_job(job)
            return job

        started = time.perf_counter()
        self.repo.clear_job_assets(job.id, job.document_id)  # clean slate; OCR cache preserved
        job.status = "processing"; job.stage = "validating"; job.progress = 1; job.error = None
        job.attempts += 1
        self._reset_counters(job)
        self.repo.save_job(job)
        self.repo.log(job, "pipeline", "Media processing started.")

        cache = _OcrCacheView(self.db, job.document_id)
        segments: List[Dict[str, Any]] = []
        speakers: List[Dict[str, Any]] = []
        turns: List[Dict[str, Any]] = []
        scenes: List[Dict[str, Any]] = []
        frames: List[Dict[str, Any]] = []
        subtitles: List[Dict[str, Any]] = []
        meta_ev: Dict[str, Any] = {}
        stage_latency: Dict[str, int] = {}
        cache_hits = 0
        current_stage = "validating"

        try:
            for ev in engine.process(job, doc, storage, cache):
                etype = ev.get("type")
                if etype == "classification":
                    job.media_kind = ev.get("media_kind", job.media_kind)
                    job.media_category = ev.get("media_category", "unknown")
                    job.category_confidence = ev.get("category_confidence")
                    job.language = ev.get("language", "") or job.language
                    self.repo.save_job(job)
                    self.repo.log(job, "classification",
                                  f"Classified as {job.media_kind}/{job.media_category}.")
                elif etype == "metadata":
                    meta_ev = ev
                    self._apply_metadata(job, ev)
                    self.repo.save_job(job)
                elif etype == "stage":
                    if self.repo.job_status(job.id) == "cancelled":
                        job.stage = "cancelled"; self.repo.save_job(job)
                        self.repo.log(job, "pipeline", "Cancelled by user.", "warn")
                        return job
                    current_stage = ev.get("stage", job.stage)
                    job.stage = current_stage
                    job.progress = int(ev.get("progress", job.progress))
                    if ev.get("latency_ms") is not None:
                        stage_latency[current_stage] = int(ev["latency_ms"])
                    self.repo.save_job(job)
                elif etype == "transcript":
                    segments.append(ev)
                elif etype == "speaker":
                    speakers.append(ev)
                elif etype == "turn":
                    turns.append(ev)
                elif etype == "scene":
                    scenes.append(ev)
                elif etype == "frame":
                    frames.append(self._buffer_frame(job, storage, ev))
                    if ev.get("cached"):
                        cache_hits += 1
                    else:
                        self._cache_frame_ocr(job, ev)
                elif etype == "subtitle":
                    subtitles.append(ev)
                elif etype == "final":
                    job.pipeline_version = ev.get("pipeline_version", job.pipeline_version)

            # --- finalization: resolve cross-references + persist ---
            self._finalize(job, doc, segments, speakers, turns, scenes, frames, subtitles,
                           meta_ev, stage_latency, cache_hits, started)
        except Exception as e:  # failure recovery — keep partial assets, record the error
            job.status = "failed"; job.stage = "failed"; job.error = str(e)[:4000]
            job.processing_ms = int((time.perf_counter() - started) * 1000)
            self.repo.save_job(job)
            self.repo.log(job, "pipeline", f"Failed: {e}", "error")
            return job
        return job

    # ------------------------------------------------------------------ finalization
    def _finalize(self, job, doc, segments, speakers, turns, scenes, frames, subtitles,
                  meta_ev, stage_latency, cache_hits, started) -> None:
        job.stage = "persisting"; job.progress = 95; self.repo.save_job(job)

        # 1) speakers → rows + label→id map
        speaker_rows = [Speaker(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            speaker_label=s.get("speaker_label", ""), total_speaking_ms=int(s.get("total_speaking_ms", 0)),
            turn_count=int(s.get("turn_count", 0)), confidence=s.get("confidence"),
        ) for s in speakers]
        self.repo.add_speakers(speaker_rows)
        label_to_id = {r.speaker_label: r.id for r in speaker_rows}

        # 2) scenes → rows + index→id map (representative frame resolved after frames persist)
        scene_rows: List[Scene] = []
        scene_index_to_id: Dict[int, str] = {}
        for sc in sorted(scenes, key=lambda x: int(x.get("start_ms", 0))):
            start_ms, end_ms = int(sc.get("start_ms", 0)), int(sc.get("end_ms", 0))
            row = Scene(job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
                        scene_index=int(sc.get("scene_index", 0)), start_ms=start_ms, end_ms=end_ms,
                        duration_ms=max(0, end_ms - start_ms), score=sc.get("score"))
            scene_rows.append(row)
        self.repo.add_scenes(scene_rows)
        for row in scene_rows:
            scene_index_to_id[row.scene_index] = row.id

        # 3) frames → rows (resolve scene_id), write already done during streaming
        frame_rows: List[MediaFrame] = []
        for fr in sorted(frames, key=lambda x: int(x.get("timestamp_ms", 0))):
            sidx = fr.get("scene_index")
            preset_id = fr.get("_preset_id")
            row = MediaFrame(
                **({"id": preset_id} if preset_id else {}),
                job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
                frame_index=int(fr.get("frame_index", 0)), timestamp_ms=int(fr.get("timestamp_ms", 0)),
                scene_id=scene_index_to_id.get(sidx) if sidx is not None else None, scene_index=sidx,
                width=int(fr.get("width", 0)), height=int(fr.get("height", 0)), hash=fr.get("hash", ""),
                storage_path=fr.get("storage_path", ""), is_keyframe=bool(fr.get("is_keyframe", False)),
                extraction=fr.get("extraction", "periodic"), ocr_text=fr.get("ocr_text") or None,
                ocr_confidence=fr.get("ocr_confidence"))
            self.repo.add_frame(row)
            fr["id"] = row.id
            fr["scene_id"] = row.scene_id
            frame_rows.append(row)

        # 3b) resolve each scene's representative frame (first frame in the scene)
        first_frame_by_scene: Dict[str, str] = {}
        for row in frame_rows:
            if row.scene_id and row.scene_id not in first_frame_by_scene:
                first_frame_by_scene[row.scene_id] = row.id
        for row in scene_rows:
            rep = first_frame_by_scene.get(row.id)
            if rep:
                row.representative_frame_id = rep
        self.repo.save()

        # 4) transcript segments (resolve speaker_id), compute speaker segment_count
        seg_count_by_speaker: Dict[str, int] = {}
        segment_rows: List[TranscriptSegment] = []
        for i, seg in enumerate(sorted(segments, key=lambda x: (int(x.get("start_ms", 0)),
                                                                int(x.get("segment_index", 0))))):
            label = seg.get("speaker_label", "") or ""
            sid = label_to_id.get(label)
            seg["speaker_id"] = sid
            seg["id"] = None  # filled after insert for chunk linkage below (not required)
            row = TranscriptSegment(
                job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
                segment_index=int(seg.get("segment_index", i)), start_ms=int(seg.get("start_ms", 0)),
                end_ms=int(seg.get("end_ms", 0)), text=(seg.get("text", "") or "")[:20000],
                speaker_id=sid, speaker_label=label, confidence=seg.get("confidence"),
                no_speech_prob=seg.get("no_speech_prob"), language=seg.get("language", "") or job.language,
                words=seg.get("words"))
            segment_rows.append(row)
            if sid:
                seg_count_by_speaker[sid] = seg_count_by_speaker.get(sid, 0) + 1
        self.repo.add_segments(segment_rows)
        for r in speaker_rows:
            r.segment_count = seg_count_by_speaker.get(r.id, 0)
        self.repo.save()

        # 5) turns (resolve speaker_id)
        turn_rows = []
        for ti, t in enumerate(sorted(turns, key=lambda x: int(x.get("start_ms", 0)))):
            turn_rows.append(SpeakerTurn(
                job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
                speaker_id=label_to_id.get(t.get("speaker_label", "")),
                speaker_label=t.get("speaker_label", ""), turn_index=ti,
                start_ms=int(t.get("start_ms", 0)), end_ms=int(t.get("end_ms", 0))))
        self.repo.add_turns(turn_rows)

        # 6) subtitles
        subtitle_rows = [Subtitle(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            subtitle_index=int(s.get("subtitle_index", i)), start_ms=int(s.get("start_ms", 0)),
            end_ms=int(s.get("end_ms", 0)), text=(s.get("text", "") or "")[:5000],
            source=s.get("source", "embedded"), language=s.get("language", "") or job.language,
        ) for i, s in enumerate(subtitles)]
        self.repo.add_subtitles(subtitle_rows)

        # 7) unified temporal chunks
        job.stage = "chunking"; job.progress = 97; self.repo.save_job(job)
        chunk_dicts = build_media_chunks(
            segments=[{**s, "speaker_id": s.get("speaker_id")} for s in segments],
            speakers=[{"id": r.id, "speaker_label": r.speaker_label, "display_name": r.display_name,
                       "total_speaking_ms": r.total_speaking_ms, "turn_count": r.turn_count} for r in speaker_rows],
            scenes=[{"id": r.id, "scene_index": r.scene_index, "start_ms": r.start_ms, "end_ms": r.end_ms,
                     "duration_ms": r.duration_ms, "representative_frame_id": r.representative_frame_id,
                     "ocr_text": None} for r in scene_rows],
            subtitles=[{"id": r.id, "start_ms": r.start_ms, "end_ms": r.end_ms, "text": r.text,
                        "source": r.source, "language": r.language} for r in subtitle_rows],
            frames=[{"id": fr.get("id"), "timestamp_ms": fr.get("timestamp_ms"),
                     "scene_id": fr.get("scene_id"), "is_keyframe": fr.get("is_keyframe"),
                     "extraction": fr.get("extraction"), "ocr_text": fr.get("ocr_text"),
                     "ocr_confidence": fr.get("ocr_confidence")} for fr in frames],
        )
        chunk_rows = [MediaChunk(
            job_id=job.id, workspace_id=job.workspace_id, document_id=job.document_id,
            chunk_type=c["chunk_type"], source=c["source"], chunk_index=c["chunk_index"],
            start_ms=c["start_ms"], end_ms=c["end_ms"], speaker_id=c.get("speaker_id"),
            scene_id=c.get("scene_id"), asset_id=c.get("asset_id"), content=c["content"][:20000],
            meta=c.get("meta"), embedding_status="pending") for c in chunk_dicts]
        self.repo.add_chunks(chunk_rows)

        # 8) finalize counters + metadata
        word_count = sum(len((s.get("text", "") or "").split()) for s in segments)
        transcript_chars = sum(len(s.get("text", "") or "") for s in segments)
        confs = [s.get("confidence") for s in speakers if s.get("confidence") is not None]
        seg_confs = [s.get("confidence") for s in segments if s.get("confidence") is not None]

        job.segment_count = len(segment_rows)
        job.speaker_count = len(speaker_rows)
        job.scene_count = len(scene_rows)
        job.frame_count = len(frame_rows)
        job.subtitle_count = len(subtitle_rows)
        job.ocr_frame_count = sum(1 for fr in frames if (fr.get("ocr_text") or "").strip())
        job.chunk_count = len(chunk_rows)
        job.word_count = word_count
        job.transcript_chars = transcript_chars
        job.avg_speech_rate = _speech_rate(word_count, job.duration_ms)
        job.transcription_confidence = round(sum(seg_confs) / len(seg_confs), 4) if seg_confs else None
        job.cache_hits = cache_hits
        for k, v in stage_latency.items():
            _set_stage_latency(job, k, v)
        job.processing_ms = int((time.perf_counter() - started) * 1000)
        job.status = "completed"; job.stage = "completed"; job.progress = 100
        self.repo.save_job(job)
        self.repo.log(job, "pipeline",
                      f"Completed: {job.segment_count} segments, {job.speaker_count} speakers, "
                      f"{job.scene_count} scenes, {job.frame_count} frames, {job.subtitle_count} subtitles, "
                      f"{job.chunk_count} chunks.")
        self._update_document(doc, job)

    # ------------------------------------------------------------------ streaming persistence
    def _buffer_frame(self, job, storage, ev) -> Dict[str, Any]:
        """Write a frame's bytes to storage immediately (stream), buffer its metadata for finalize."""
        data = ev.get("bytes", b"")
        frame_id = None
        storage_path = ""
        if data:
            # Use a stable id so storage + row line up; generate one now.
            from app.media.models import _asset_id
            frame_id = _asset_id("frm")
            storage_path = storage.write_frame(job.workspace_id, job.document_id, frame_id, data,
                                               ev.get("ext", "jpg"))
        return {"frame_index": ev.get("frame_index", 0), "timestamp_ms": ev.get("timestamp_ms", 0),
                "scene_index": ev.get("scene_index"), "width": ev.get("width", 0),
                "height": ev.get("height", 0), "hash": ev.get("hash", ""), "storage_path": storage_path,
                "is_keyframe": ev.get("is_keyframe", False), "extraction": ev.get("extraction", "periodic"),
                "ocr_text": ev.get("ocr_text"), "ocr_confidence": ev.get("ocr_confidence"),
                "_preset_id": frame_id}

    def _cache_frame_ocr(self, job, ev) -> None:
        """Persist frame OCR into the reused Phase-4 OcrResult cache (never re-run for same frame)."""
        text = (ev.get("ocr_text") or "").strip()
        content_hash = ev.get("content_hash") or ev.get("hash", "")
        if not text or not content_hash:
            return
        from app.ingestion.models import OcrResult
        from app.ingestion.repository import IngestionRepository
        repo = IngestionRepository(self.db)
        page = int(ev.get("frame_index", 0))
        if repo.get_ocr(job.document_id, page, content_hash) is None:
            repo.add_ocr(OcrResult(
                workspace_id=job.workspace_id, document_id=job.document_id, page_number=page,
                content_hash=content_hash, text=text, confidence=ev.get("ocr_confidence"),
                language=job.language, boxes=None, reading_order=None))

    def _update_document(self, doc, job) -> None:
        """Reflect media processing on the Document row (does NOT alter text retrieval)."""
        from app.documents.repository import DocumentRepository
        doc.processing_status = "completed"
        doc.processing_stage = "completed"
        doc.processing_ms = job.processing_ms
        doc.language = job.language or doc.language
        doc.chunk_count = job.chunk_count
        if job.ocr_frame_count > 0:
            doc.ocr_status = "completed"
        DocumentRepository(self.db).save(doc)

    # ------------------------------------------------------------------ small mutators
    def _reset_counters(self, job) -> None:
        job.segment_count = job.speaker_count = job.scene_count = job.frame_count = 0
        job.subtitle_count = job.ocr_frame_count = job.chunk_count = job.word_count = 0
        job.transcript_chars = job.cache_hits = 0
        job.transcribe_ms = job.diarize_ms = job.frames_ms = job.scenes_ms = 0
        job.ocr_ms = job.subtitles_ms = job.chunk_ms = 0

    def _apply_metadata(self, job, ev) -> None:
        job.duration_ms = int(ev.get("duration_ms", 0) or 0)
        job.width = int(ev.get("width", 0) or 0)
        job.height = int(ev.get("height", 0) or 0)
        job.fps = ev.get("fps")
        job.sample_rate = int(ev.get("sample_rate", 0) or 0)
        job.channels = int(ev.get("channels", 0) or 0)
        job.video_codec = ev.get("video_codec", "") or ""
        job.audio_codec = ev.get("audio_codec", "") or ""
        job.container = ev.get("container", "") or ""
        job.bitrate = int(ev.get("bitrate", 0) or 0)

    # ------------------------------------------------------------------ commands
    def retry(self, job_id: str, owner_id: str) -> MediaJob:
        job = self._job_or_404(job_id, owner_id)
        if job.status not in ("failed", "cancelled"):
            raise MediaStateError(f"Cannot retry a '{job.status}' job.")
        job.status = "queued"; job.stage = "queued"; job.progress = 0; job.error = None
        return self.repo.save_job(job)

    def cancel(self, job_id: str, owner_id: str) -> MediaJob:
        job = self._job_or_404(job_id, owner_id)
        if job.status not in ("queued", "processing"):
            raise MediaStateError(f"Cannot cancel a '{job.status}' job.")
        job.status = "cancelled"; job.stage = "cancelled"
        return self.repo.save_job(job)

    # ------------------------------------------------------------------ queries
    def get(self, job_id: str, owner_id: str) -> MediaJob:
        return self._job_or_404(job_id, owner_id)

    def detail(self, job_id: str, owner_id: str):
        job = self._job_or_404(job_id, owner_id)
        return job, self.repo.logs_for(job.id)

    def status_for_document(self, document_id: str, owner_id: str, workspace_id: str) -> Optional[MediaJob]:
        self._document(document_id, owner_id, workspace_id)
        return self.repo.latest_job_for_document(document_id, owner_id)

    def transcript(self, document_id: str, owner_id: str, workspace_id: str,
                   speaker_id: Optional[str] = None):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.segments_for(document_id, speaker_id)

    def speakers(self, document_id: str, owner_id: str, workspace_id: str):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.speakers_for(document_id), self.repo.turns_for(document_id)

    def frames(self, document_id: str, owner_id: str, workspace_id: str, scene_id: Optional[str] = None):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.frames_for(document_id, scene_id)

    def frame(self, document_id: str, owner_id: str, workspace_id: str, frame_id: str):
        self._document(document_id, owner_id, workspace_id)
        row = self.repo.frame(frame_id)
        if row is None or row.document_id != document_id:
            raise MediaNotFound(frame_id)
        return row

    def scenes(self, document_id: str, owner_id: str, workspace_id: str):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.scenes_for(document_id)

    def subtitles(self, document_id: str, owner_id: str, workspace_id: str):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.subtitles_for(document_id)

    def chunks(self, document_id: str, owner_id: str, workspace_id: str, chunk_type: Optional[str] = None):
        self._document(document_id, owner_id, workspace_id)
        return self.repo.chunks_for(document_id, chunk_type)

    def metadata(self, document_id: str, owner_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        self._document(document_id, owner_id, workspace_id)
        job = self.repo.latest_job_for_document(document_id, owner_id)
        if job is None:
            return None
        return build_metadata(
            media_kind=job.media_kind, media_category=job.media_category, language=job.language,
            duration_ms=job.duration_ms, width=job.width, height=job.height, fps=job.fps,
            sample_rate=job.sample_rate, channels=job.channels, video_codec=job.video_codec,
            audio_codec=job.audio_codec, container=job.container, bitrate=job.bitrate,
            speaker_count=job.speaker_count, scene_count=job.scene_count, frame_count=job.frame_count,
            subtitle_count=job.subtitle_count, segment_count=job.segment_count,
            ocr_frame_count=job.ocr_frame_count, chunk_count=job.chunk_count,
            transcript_chars=job.transcript_chars, word_count=job.word_count,
            transcription_confidence=job.transcription_confidence, processing_ms=job.processing_ms,
            stage_latencies={"transcribe_ms": job.transcribe_ms, "diarize_ms": job.diarize_ms,
                             "frames_ms": job.frames_ms, "scenes_ms": job.scenes_ms,
                             "ocr_ms": job.ocr_ms, "subtitles_ms": job.subtitles_ms,
                             "chunk_ms": job.chunk_ms}, cache_hits=job.cache_hits)


def _speech_rate(word_count: int, duration_ms: int) -> float | None:
    if not duration_ms or duration_ms <= 0:
        return None
    minutes = duration_ms / 60_000.0
    return round(word_count / minutes, 2) if minutes > 0 else None


def _set_stage_latency(job, stage: str, ms: int) -> None:
    mapping = {"transcription": "transcribe_ms", "diarization": "diarize_ms",
               "frame_extraction": "frames_ms", "scene_detection": "scenes_ms",
               "ocr": "ocr_ms", "subtitles": "subtitles_ms", "chunking": "chunk_ms"}
    attr = mapping.get(stage)
    if attr:
        setattr(job, attr, int(ms))
