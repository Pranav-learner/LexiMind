"""Audio & Video media domain (Phase 5, Module 1: Audio & Video Processing Engine).

The ingestion foundation for every FUTURE temporal-intelligence capability. It turns a raw recording
(audio: mp3/wav/m4a/flac/aac · video: mp4/mkv/mov/avi/webm) into structured, timestamp-aware
knowledge — media classification, container/codec metadata, speech-to-text transcript, speaker
diarization + conversation turns, scene detection, representative-frame extraction, on-screen OCR
(reusing the Phase-4 OCR backend), embedded subtitles, and unified temporal chunks — WITHOUT touching
the Phase-1 text retrieval pipeline or the Phase-2/4 context engine (chunks land in a future embedding
queue with `embedding_status="pending"`; retrieval/context adapters are declared but not wired).

    models.py         9 tables: MediaJob / TranscriptSegment / Speaker / SpeakerTurn / MediaFrame /
                      Scene / Subtitle / MediaChunk / MediaProcessingLog
    validation.py     supported audio/video registry + validators (easy-to-extend)
    classification.py pure media-category heuristics (lecture/meeting/podcast/...)
    storage.py        media asset hierarchy (reuses Phase-4 AssetStorage)
    chunking.py       pure temporal chunk builder (speaker-coherent transcript windows + scene/sub/ocr)
    metadata.py       pure temporal-metadata assembly
    engines.py        the ONLY bridge to ffmpeg/whisper/pyannote/scenedetect/opencv — injected, lazy
                      (FakeMediaEngine + PipelineMediaEngine); frame OCR reuses ingestion's backend
    repository.py     all SQL for the media tables (frame-OCR cache reuses Phase-4 OcrResult)
    service.py        the staged async pipeline (validate→classify→metadata→ASR→diarize→scenes→
                      frames→ocr→subtitles→temporal-chunk→metadata→queue)
    interfaces.py     future retrieval + context seams (declared, intentionally NOT wired)
    runner.py         background execution (threadpool prod runner + inline test runner)
    api.py            authenticated routes under /workspaces/{id}/media (upload + status + outputs)

Business logic never lives in API handlers; the API never issues SQL directly; the package never
imports A/V libraries (the engine is injected) and NEVER modifies Phase-1/2/3/4 behaviour.
"""
