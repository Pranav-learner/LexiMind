"""Unit tests for temporal intelligence derivation + temporal retrieval internals — pure/offline.

Covers tintel derivation, temporal query analysis (incl. timestamp/relative-order parsing), fusion
(dedup + temporal adjacency), reranking, timeline-aware context assembly + timestamp-preserving
compression, the adaptive prompt builder, and temporal citations. No ffmpeg/whisper/faiss/torch.
"""

from __future__ import annotations

from app.tintel.derivation import derive_chapters, derive_events, derive_topics, top_keywords
from app.tretrieval.citations import build_citations
from app.tretrieval.context import build_context, temporal_dedup
from app.tretrieval.fusion import fuse
from app.tretrieval.intent import analyze, parse_time
from app.tretrieval.prompt import build_prompt
from app.tretrieval.rerank import LexicalTemporalReranker
from app.tretrieval.schemas import TemporalHit


# --------------------------------------------------------------------- tintel derivation
_SEGS = [
    {"start_ms": 0, "end_ms": 5000, "text": "deadlocks and scheduling in operating systems", "speaker_label": "SPEAKER_00"},
    {"start_ms": 5000, "end_ms": 10000, "text": "memory management and paging techniques here", "speaker_label": "SPEAKER_01"},
    {"start_ms": 10000, "end_ms": 15000, "text": "memory management continues with segmentation", "speaker_label": "SPEAKER_01"},
]
_SCENES = [{"id": "scn1", "scene_index": 0, "start_ms": 0, "end_ms": 6000},
           {"id": "scn2", "scene_index": 1, "start_ms": 6000, "end_ms": 15000}]
_TURNS = [{"start_ms": 0, "end_ms": 5000, "speaker_label": "SPEAKER_00", "speaker_id": "a"},
          {"start_ms": 5000, "end_ms": 15000, "speaker_label": "SPEAKER_01", "speaker_id": "b"}]


def test_top_keywords_drops_stopwords():
    kws = top_keywords("the memory management and the paging memory", 3)
    assert "memory" in kws
    assert "the" not in kws and "and" not in kws


def test_derive_chapters_scene_aligned():
    chapters = derive_chapters(_SEGS, _SCENES, 15000)
    assert len(chapters) == 2                     # one per scene
    assert chapters[0]["start_ms"] == 0 and chapters[0]["end_ms"] == 6000
    assert chapters[0]["keywords"]                # titled from transcript keywords


def test_derive_chapters_fixed_window_when_no_scenes():
    chapters = derive_chapters(_SEGS, [], 15000)
    assert len(chapters) >= 1
    assert chapters[0]["start_ms"] == 0


def test_derive_topics_groups_by_dominant_keyword():
    topics = derive_topics(_SEGS)
    assert len(topics) >= 1
    assert all(t["end_ms"] >= t["start_ms"] for t in topics)
    assert sum(t["salience"] for t in topics) <= 1.0001


def test_derive_events_merges_and_orders():
    chapters = derive_chapters(_SEGS, _SCENES, 15000)
    topics = derive_topics(_SEGS)
    events = derive_events(_SEGS, _TURNS, _SCENES, chapters, topics)
    types = {e["event_type"] for e in events}
    assert "chapter_start" in types and "scene_change" in types and "speaker_change" in types
    ts = [e["timestamp_ms"] for e in events]
    assert ts == sorted(ts)                       # chronological
    assert [e["event_index"] for e in events] == list(range(len(events)))


# --------------------------------------------------------------------- query analysis
def test_parse_time_formats():
    assert parse_time("what about at 12:04").anchor_ms == (12 * 60 + 4) * 1000
    assert parse_time("around 1:02:03").anchor_ms == (3600 + 2 * 60 + 3) * 1000
    assert parse_time("after 45 minutes").anchor_ms == 45 * 60_000
    assert parse_time("no time here") is None


def test_analyze_detects_speaker_topic_timestamp():
    it = analyze("What did the professor say about deadlocks at 12:04?")
    assert "speaker" in it.detected and "topic" in it.detected and "timestamp" in it.detected
    assert it.query_type == "timestamp"
    assert it.time_filter is not None


def test_analyze_relative_order_is_timeline():
    it = analyze("What happened after the scheduling discussion?")
    assert it.order == "after"
    assert "event" in it.detected
    assert it.query_type == "timeline"
    assert "transcript" in it.modalities          # always searched


# --------------------------------------------------------------------- fusion
def _hit(key, modality, score, start, end, **kw):
    h = TemporalHit(key=key, modality=modality, source_type=modality, document_id=kw.get("doc", "doc1"),
                    content=kw.get("content", "content"), start_ms=start, end_ms=end,
                    speaker_label=kw.get("spk", ""))
    h.normalized_score = score
    h.rank_in_modality = kw.get("rank", 1)
    return h


def test_fusion_merges_same_key_across_modalities():
    a = _hit("seg:1", "transcript", 1.0, 0, 5000, rank=1)
    b = _hit("seg:1", "timestamp", 0.8, 0, 5000, rank=1)
    fused = fuse({"transcript": [a], "timestamp": [b]}, {"transcript": 1.0, "timestamp": 0.9})
    assert len(fused) == 1
    assert set(fused[0].contributing_modalities) == {"transcript", "timestamp"}


def test_fusion_temporal_adjacency_bonus():
    top = _hit("seg:1", "transcript", 1.0, 0, 5000, rank=1)
    near = _hit("seg:2", "transcript", 0.5, 6000, 11000, rank=2)   # within 30s of top
    far = _hit("seg:3", "transcript", 0.5, 600000, 605000, rank=3)  # far away
    fused = fuse({"transcript": [top, near, far]}, {"transcript": 1.0})
    near_hit = next(h for h in fused if h.key == "seg:2")
    far_hit = next(h for h in fused if h.key == "seg:3")
    assert near_hit.metadata.get("temporal_adjacent") is True
    assert near_hit.fusion_score > far_hit.fusion_score


# --------------------------------------------------------------------- rerank
def test_reranker_speaker_prior_and_blend():
    hits = [_hit("seg:1", "transcript", 1.0, 0, 5000, content="deadlocks explained", spk="SPEAKER_00"),
            _hit("seg:2", "transcript", 0.9, 5000, 10000, content="unrelated chatter", spk="SPEAKER_01")]
    for h in hits:
        h.fusion_score = h.normalized_score
    ranked = LexicalTemporalReranker().rerank("deadlocks", ["deadlocks"], hits,
                                              primary="transcript", speaker_hint="SPEAKER_00")
    assert ranked[0].key == "seg:1"
    assert all(0.0 <= h.confidence <= 1.0 for h in ranked)


# --------------------------------------------------------------------- context + prompt + citations
def _rich_hit(key, modality, content, start, end, spk="", conf=0.8):
    h = TemporalHit(key=key, modality=modality, source_type=modality, document_id="doc1",
                    content=content, start_ms=start, end_ms=end, speaker_label=spk)
    h.confidence = conf
    h.metadata = {"timespan": "0:00–0:05"}
    return h


def test_temporal_dedup_merges_overlapping_same_speaker():
    a = _rich_hit("a", "transcript", "the memory management model works", 0, 5000, spk="S0")
    b = _rich_hit("b", "transcript", "the memory management model works", 0, 5000, spk="S0")  # dup
    c = _rich_hit("c", "transcript", "completely different content about paging", 0, 5000, spk="S0")
    kept, removed = temporal_dedup([a, b, c])
    assert removed == 1 and len(kept) == 2


def test_build_context_orders_by_time_and_preserves_timestamps():
    hits = [_rich_hit("b", "transcript", "second moment discussing scheduling", 10000, 15000, conf=0.9),
            _rich_hit("a", "transcript", "first moment discussing deadlocks", 0, 5000, conf=0.7)]
    blocks, stats = build_context(hits, ["deadlocks", "scheduling"], total_budget=500)
    assert stats["included"] == 2
    assert blocks[0].start_ms == 0 and blocks[1].start_ms == 10000   # chronological
    assert blocks[0].citation_index == 1                            # re-indexed after assembly


def test_build_prompt_adapts_and_tags_timestamps():
    hits = [_rich_hit("a", "transcript", "deadlocks occur when processes wait", 0, 5000, spk="SPEAKER_00")]
    blocks, _ = build_context(hits, ["deadlocks"], total_budget=500)
    system, user, cits = build_prompt("what about deadlocks", "speaker", blocks)
    assert "speaker" in system.lower()
    assert "[1]" in user and "Question:" in user
    assert len(cits) == 1


def test_build_citations_carry_time_and_speaker():
    hits = [_rich_hit("a", "transcript", "content here", 3000, 8000, spk="SPEAKER_01")]
    blocks, _ = build_context(hits, ["content"], total_budget=500)
    cits = build_citations(blocks)
    assert cits[0]["speaker_label"] == "SPEAKER_01"
    assert cits[0]["start_ms"] == 3000 and cits[0]["index"] == 1
