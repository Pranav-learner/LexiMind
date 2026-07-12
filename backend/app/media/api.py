"""Media (audio/video) HTTP routes — thin transport over MediaService + a background runner.

Authenticated + workspace-scoped. Processing is asynchronous: `POST .../media` uploads a recording,
creates a `queued` job, and hands the id to the injected runner; the client polls
`GET .../media/{document_id}/status`. The runner (and the engine it wraps) are injected lazily so
`app.media.api` imports with no ffmpeg/whisper/etc. and tests substitute an inline runner + fake
engine. Consistent with `app.ingestion.api` and `app.vision.api`.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.core.config import settings
from app.db.base import get_db
from app.media.errors import MediaError
from app.media.metadata import speaker_timeline
from app.media.repository import MediaRepository
from app.media.schemas import (
    MediaChunkOut,
    MediaFrameOut,
    MediaJobDetail,
    MediaJobOut,
    MediaProcessingLogOut,
    OcrFrameOut,
    OcrResponse,
    ProcessRequest,
    SceneOut,
    SpeakerOut,
    SpeakerTimelineResponse,
    SpeakerTurnOut,
    SubtitleOut,
    TranscriptResponse,
    TranscriptSegmentOut,
    UploadResponse,
)
from app.media.service import MediaService
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/media", tags=["media"])

_runner = None


def get_media_runner():
    global _runner
    if _runner is None:
        from app.media.runner import MediaRunner
        _runner = MediaRunner()
    return _runner


def _service(db: Session) -> MediaService:
    return MediaService(MediaRepository(db))


def _handle(fn):
    try:
        return fn()
    except MediaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _job_out(job) -> MediaJobOut:
    return MediaJobOut.model_validate(job)


def _media_dir(workspace_id: str) -> str:
    # Store media alongside document uploads (per-workspace), reusing the configured upload dir.
    return os.path.join(settings.upload_dir, workspace_id)


# ----------------------------------------------------------------- upload (async)
@router.post("", response_model=UploadResponse, status_code=201)
async def upload_media(
    workspace_id: str,
    file: UploadFile = File(...),
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    runner=Depends(get_media_runner),
):
    """Upload an audio/video recording, register it as a media Document, and enqueue processing."""
    _verify_workspace(db, workspace_id, owner_id)
    data = await file.read()
    service = _service(db)
    job = _handle(lambda: service.upload(
        owner_id, workspace_id, filename=file.filename or "untitled", data=data,
        storage_dir_factory=_media_dir))
    if job.status == "queued":
        runner.submit(job.id)
        db.refresh(job)
    return UploadResponse(document_id=job.document_id, filename=file.filename or "untitled",
                          media_kind=job.media_kind, job=_job_out(job))


# ----------------------------------------------------------------- reprocess (async)
@router.post("/{document_id}/process", response_model=MediaJobOut, status_code=202)
def process_media(
    workspace_id: str, document_id: str, req: ProcessRequest = ProcessRequest(),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
    runner=Depends(get_media_runner),
):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).create_or_get_job(owner_id, workspace_id, document_id, force=req.force))
    if job.status == "queued":
        runner.submit(job.id)
        db.refresh(job)
    return _job_out(job)


# ----------------------------------------------------------------- status / outputs
@router.get("/{document_id}/status", response_model=MediaJobOut | None)
def media_status(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).status_for_document(document_id, owner_id, workspace_id))
    return _job_out(job) if job else None


@router.get("/{document_id}/transcript", response_model=TranscriptResponse)
def media_transcript(
    workspace_id: str, document_id: str, speaker_id: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    segs = _handle(lambda: _service(db).transcript(document_id, owner_id, workspace_id, speaker_id))
    lang = next((s.language for s in segs if s.language), "")
    duration = max((s.end_ms for s in segs), default=0)
    return TranscriptResponse(
        document_id=document_id, language=lang, segment_count=len(segs), duration_ms=duration,
        segments=[TranscriptSegmentOut.model_validate(s) for s in segs])


@router.get("/{document_id}/speakers", response_model=SpeakerTimelineResponse)
def media_speakers(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    speakers, turns = _handle(lambda: _service(db).speakers(document_id, owner_id, workspace_id))
    tl = speaker_timeline([{"speaker_label": t.speaker_label, "speaker_id": t.speaker_id,
                            "start_ms": t.start_ms, "end_ms": t.end_ms} for t in turns])
    return SpeakerTimelineResponse(
        document_id=document_id, speaker_count=len(speakers),
        speakers=[SpeakerOut.model_validate(s) for s in speakers],
        timeline=[SpeakerTurnOut(speaker_id=t["speaker_id"], speaker_label=t["speaker_label"],
                                 turn_index=i, start_ms=t["start_ms"], end_ms=t["end_ms"])
                  for i, t in enumerate(tl)])


@router.get("/{document_id}/frames", response_model=list[MediaFrameOut])
def media_frames(
    workspace_id: str, document_id: str, scene_id: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    frames = _handle(lambda: _service(db).frames(document_id, owner_id, workspace_id, scene_id))
    return [MediaFrameOut.model_validate(f) for f in frames]


@router.get("/{document_id}/frames/{frame_id}/thumbnail")
def media_frame_thumbnail(workspace_id: str, document_id: str, frame_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    frame = _handle(lambda: _service(db).frame(document_id, owner_id, workspace_id, frame_id))
    if not frame.storage_path or not os.path.exists(frame.storage_path):
        raise HTTPException(status_code=404, detail="Frame image is not available.")
    return FileResponse(frame.storage_path, media_type="image/jpeg")


@router.get("/{document_id}/scenes", response_model=list[SceneOut])
def media_scenes(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    scenes = _handle(lambda: _service(db).scenes(document_id, owner_id, workspace_id))
    return [SceneOut.model_validate(s) for s in scenes]


@router.get("/{document_id}/subtitles", response_model=list[SubtitleOut])
def media_subtitles(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    subs = _handle(lambda: _service(db).subtitles(document_id, owner_id, workspace_id))
    return [SubtitleOut.model_validate(s) for s in subs]


@router.get("/{document_id}/ocr", response_model=OcrResponse)
def media_ocr(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    frames = _handle(lambda: _service(db).frames(document_id, owner_id, workspace_id))
    ocr_frames = [f for f in frames if (f.ocr_text or "").strip()]
    return OcrResponse(
        document_id=document_id, ocr_frame_count=len(ocr_frames),
        frames=[OcrFrameOut(id=f.id, frame_index=f.frame_index, timestamp_ms=f.timestamp_ms,
                            ocr_text=f.ocr_text or "", ocr_confidence=f.ocr_confidence) for f in ocr_frames])


@router.get("/{document_id}/chunks", response_model=list[MediaChunkOut])
def media_chunks(
    workspace_id: str, document_id: str, chunk_type: str | None = Query(None),
    owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    chunks = _handle(lambda: _service(db).chunks(document_id, owner_id, workspace_id, chunk_type))
    return [MediaChunkOut.model_validate(c) for c in chunks]


@router.get("/{document_id}/metadata")
def media_metadata(workspace_id: str, document_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    meta = _handle(lambda: _service(db).metadata(document_id, owner_id, workspace_id))
    if meta is None:
        raise HTTPException(status_code=404, detail="No processing metadata yet for this media.")
    return meta


# ----------------------------------------------------------------- job-level (detail / retry / cancel)
@router.get("/jobs/{job_id}", response_model=MediaJobDetail)
def job_detail(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    job, logs = _handle(lambda: _service(db).detail(job_id, owner_id))
    d = MediaJobDetail.model_validate(job)
    d.logs = [MediaProcessingLogOut.model_validate(x) for x in logs]
    return d


@router.post("/jobs/{job_id}/retry", response_model=MediaJobOut)
def retry_job(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db), runner=Depends(get_media_runner)):
    _verify_workspace(db, workspace_id, owner_id)
    job = _handle(lambda: _service(db).retry(job_id, owner_id))
    runner.submit(job.id)
    db.refresh(job)
    return _job_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=MediaJobOut)
def cancel_job(workspace_id: str, job_id: str, owner_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _verify_workspace(db, workspace_id, owner_id)
    return _job_out(_handle(lambda: _service(db).cancel(job_id, owner_id)))
