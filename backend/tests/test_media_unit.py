"""Unit tests for the media (audio/video) processing engine — pure/offline, no A/V libraries.

Covers validation, classification, temporal chunking, metadata assembly, the FakeMediaEngine event
contract, and the future-integration seam adapters.
"""

from __future__ import annotations

import pytest

from app.media import validation
from app.media.chunking import MAX_WORDS, build_media_chunks
from app.media.classification import ClassificationSignals, classify
from app.media.engines import FakeMediaEngine, _parse_vtt, _ts_to_ms
from app.media.errors import MediaTooLarge, MediaValidationError, UnsupportedMedia
from app.media.interfaces import TemporalUnit, to_context_evidence, to_temporal_units
from app.media.metadata import average_speech_rate, build_metadata, speaker_timeline


# --------------------------------------------------------------------- validation
def test_validate_supported_accepts_audio_and_video():
    assert validation.validate_supported("mp3") == "mp3"
    assert validation.validate_supported("MP4") == "mp4"
    assert validation.media_kind("wav") == "audio"
    assert validation.media_kind("mkv") == "video"


def test_validate_supported_rejects_unknown_and_future_sources():
    with pytest.raises(UnsupportedMedia):
        validation.validate_supported("pdf")
    with pytest.raises(UnsupportedMedia):
        validation.validate_supported("youtube")  # declared future source, not yet processed


def test_validate_size_bounds():
    with pytest.raises(MediaValidationError):
        validation.validate_size(0)
    with pytest.raises(MediaTooLarge):
        validation.validate_size(10**15)
    assert validation.validate_size(1234) == 1234


def test_validate_duration_guard():
    validation.validate_duration(None)          # unknown allowed
    validation.validate_duration(1000)
    with pytest.raises(MediaValidationError):
        validation.validate_duration(-1)


# --------------------------------------------------------------------- classification
@pytest.mark.parametrize("filename,expected", [
    ("CS101 Lecture 3.mp4", "lecture"),
    ("Team Standup 2024-01.mp4", "meeting"),
    ("The Daily Podcast Episode 12.mp3", "podcast"),
    ("React Tutorial Walkthrough.mp4", "tutorial"),
    ("Job Interview Recording.mp3", "interview"),
])
def test_classify_by_filename_keywords(filename, expected):
    cat, conf = classify(ClassificationSignals(filename=filename, media_kind="video", speaker_count=2))
    assert cat == expected
    assert conf >= 0.5


def test_classify_structural_fallback_audio_vs_video():
    # audio, many speakers → podcast
    cat, _ = classify(ClassificationSignals(filename="rec01.mp3", media_kind="audio", speaker_count=3))
    assert cat == "podcast"
    # video with screen text, single speaker → screen recording
    cat, _ = classify(ClassificationSignals(filename="rec01.mp4", media_kind="video",
                                            speaker_count=1, has_screen_text=True))
    assert cat == "screen_recording"


# --------------------------------------------------------------------- chunking
def _seg(i, start, end, text, spk):
    return {"segment_index": i, "start_ms": start, "end_ms": end, "text": text,
            "speaker_label": spk, "speaker_id": f"id_{spk}"}


def test_transcript_chunks_do_not_cross_speaker_boundaries():
    segs = [_seg(0, 0, 1000, "alpha beta", "SPEAKER_00"),
            _seg(1, 1000, 2000, "gamma delta", "SPEAKER_00"),
            _seg(2, 2000, 3000, "epsilon zeta", "SPEAKER_01")]
    chunks = build_media_chunks(segments=segs, speakers=[], scenes=[], subtitles=[], frames=[])
    transcripts = [c for c in chunks if c["chunk_type"] == "transcript"]
    assert len(transcripts) == 2  # split at the speaker change
    assert transcripts[0]["speaker_id"] == "id_SPEAKER_00"
    assert transcripts[1]["speaker_id"] == "id_SPEAKER_01"
    # each carries a temporal window
    assert transcripts[0]["start_ms"] == 0 and transcripts[0]["end_ms"] == 2000


def test_transcript_chunks_split_on_word_budget():
    big = " ".join(["word"] * (MAX_WORDS + 50))
    segs = [_seg(0, 0, 1000, big, "SPEAKER_00"), _seg(1, 1000, 2000, big, "SPEAKER_00")]
    chunks = build_media_chunks(segments=segs, speakers=[], scenes=[], subtitles=[], frames=[])
    assert len([c for c in chunks if c["chunk_type"] == "transcript"]) >= 2


def test_build_chunks_covers_all_modalities():
    chunks = build_media_chunks(
        segments=[_seg(0, 0, 1000, "hi there", "SPEAKER_00")],
        speakers=[{"id": "spk1", "speaker_label": "SPEAKER_00", "total_speaking_ms": 1000, "turn_count": 1}],
        scenes=[{"id": "scn1", "scene_index": 0, "start_ms": 0, "end_ms": 5000, "duration_ms": 5000,
                 "representative_frame_id": "frm1"}],
        subtitles=[{"id": "sub1", "start_ms": 0, "end_ms": 1000, "text": "caption text", "source": "embedded"}],
        frames=[{"id": "frm1", "timestamp_ms": 0, "scene_id": "scn1", "is_keyframe": True,
                 "extraction": "scene", "ocr_text": "slide text"}])
    types = {c["chunk_type"] for c in chunks}
    assert {"transcript", "speaker", "scene", "subtitle", "ocr"} <= types
    # chunk_index is a strict running order
    idxs = [c["chunk_index"] for c in chunks]
    assert idxs == sorted(idxs) and len(set(idxs)) == len(idxs)


# --------------------------------------------------------------------- metadata
def test_average_speech_rate():
    assert average_speech_rate(150, 60_000) == 150.0
    assert average_speech_rate(100, 0) is None


def test_build_metadata_shape():
    md = build_metadata(media_kind="video", media_category="lecture", language="en",
                        duration_ms=120_000, width=1280, height=720, fps=30.0, word_count=300,
                        speaker_count=2, scene_count=3, frame_count=3, chunk_count=10)
    assert md["media_kind"] == "video"
    assert md["video"]["width"] == 1280
    assert md["avg_speech_rate"] == 150.0
    assert md["duration_readable"] == "2:00"
    assert md["pipeline_version"].startswith("media-v")


def test_build_metadata_audio_has_no_video_block():
    md = build_metadata(media_kind="audio", media_category="podcast", language="en", duration_ms=60_000)
    assert md["video"] is None
    assert md["audio"]["sample_rate"] == 0


def test_speaker_timeline_sorted():
    tl = speaker_timeline([{"speaker_label": "B", "start_ms": 2000, "end_ms": 3000},
                           {"speaker_label": "A", "start_ms": 0, "end_ms": 1000}])
    assert [t["start_ms"] for t in tl] == [0, 2000]


# --------------------------------------------------------------------- fake engine contract
class _Doc:
    id = "doc_test"
    filename = "CS101 Lecture.mp4"
    display_name = "CS101 Lecture.mp4"
    file_type = "mp4"
    storage_path = "/nonexistent.mp4"


class _NoCache:
    def get(self, page_number, content_hash):
        return None


def test_fake_engine_emits_full_contract_for_video():
    events = list(FakeMediaEngine(media_kind="video", segments=4, speakers=2, scenes=2,
                                  subtitles=2).process(_Doc(), _Doc(), None, _NoCache()))
    types = [e["type"] for e in events]
    assert types[0] == "classification"
    assert "metadata" in types
    assert types.count("transcript") == 4
    assert types.count("speaker") == 2
    assert types.count("scene") == 2
    assert any(e["type"] == "frame" for e in events)
    assert types.count("subtitle") == 2
    assert types[-1] == "final"
    # frames carry OCR text (screen slides) so the OCR path is exercised
    assert any(e.get("ocr_text") for e in events if e["type"] == "frame")


def test_fake_engine_audio_has_no_video_stages():
    events = list(FakeMediaEngine(media_kind="audio", segments=3, speakers=1).process(
        _Doc(), _Doc(), None, _NoCache()))
    types = [e["type"] for e in events]
    assert "scene" not in types and "frame" not in types and "subtitle" not in types
    assert types.count("transcript") == 3


# --------------------------------------------------------------------- vtt parser
def test_vtt_parser():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello world\n\n00:00:05.000 --> 00:00:06.500\nSecond cue"
    cues = _parse_vtt(vtt)
    assert len(cues) == 2
    assert cues[0]["start_ms"] == 1000 and cues[0]["end_ms"] == 4000
    assert cues[0]["text"] == "Hello world"
    assert _ts_to_ms("00:01:30.500") == 90_500


# --------------------------------------------------------------------- interfaces seam
class _Chunk:
    def __init__(self):
        self.id = "mck1"; self.document_id = "doc1"; self.workspace_id = "ws1"
        self.chunk_type = "transcript"; self.content = "hi"; self.start_ms = 0; self.end_ms = 1000
        self.speaker_id = "spk1"; self.scene_id = None; self.asset_id = None; self.meta = {"k": "v"}


def test_interfaces_adapters():
    units = to_temporal_units([_Chunk()])
    assert isinstance(units[0], TemporalUnit)
    assert units[0].modality == "transcript"
    ev = to_context_evidence(units)
    assert ev[0]["start_ms"] == 0 and ev[0]["speaker_id"] == "spk1"
    assert ev[0]["modality"] == "transcript"
