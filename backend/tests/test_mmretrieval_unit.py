"""Unit tests for the multimodal retrieval primitives + retrievers (pure/DB, no faiss/torch)."""

from __future__ import annotations

from app.documents.models import Document
from app.ingestion.models import ExtractedTable, MultimodalChunk
from app.mmretrieval.fusion import fuse
from app.mmretrieval.intent import analyze_intent
from app.mmretrieval.normalize import minmax, zscore_sigmoid
from app.mmretrieval.rerank import LexicalCrossModalReranker, no_rerank
from app.mmretrieval.retrievers import (
    DiagramRetriever,
    ImageRetriever,
    MetadataRetriever,
    OcrRetriever,
    RetrievalContext,
    TableRetriever,
    lexical_score,
)
from app.mmretrieval.schemas import RetrievalHit
from app.vision.models import VisionAnalysis


# ------------------------------------------------------------------ intent
def test_intent_activates_modalities():
    assert analyze_intent("What is deadlock?").detected == []
    assert "diagram" in analyze_intent("Explain this diagram").detected
    assert "table" in analyze_intent("values in table 3").detected
    r = analyze_intent("find the architecture image")
    assert {"diagram", "image"} <= set(r.detected) and r.primary in ("diagram", "image")
    # A named modality is boosted above its base weight.
    assert r.weights["diagram"] > 0.75


# ------------------------------------------------------------------ normalization
def test_minmax_and_zscore():
    assert minmax([1, 3, 5]) == [0.0, 0.5, 1.0]
    assert minmax([]) == [] and minmax([2, 2]) == [1.0, 1.0]
    z = zscore_sigmoid([1, 2, 3])
    assert len(z) == 3 and all(0 <= x <= 1 for x in z) and z[0] < z[2]


# ------------------------------------------------------------------ fusion
def test_fusion_dedups_and_sums_contributions():
    a = RetrievalHit(key="k1", modality="text", source_type="t", document_id="d", content="x", normalized_score=1.0, rank_in_modality=1)
    b = RetrievalHit(key="k1", modality="ocr", source_type="o", document_id="d", content="xx", normalized_score=0.9, rank_in_modality=1)
    c = RetrievalHit(key="k2", modality="image", source_type="i", document_id="d", content="y", normalized_score=0.5, rank_in_modality=2)
    fused = fuse({"text": [a], "ocr": [b], "image": [c]}, {"text": 1.0, "ocr": 0.8, "image": 0.7})
    assert len(fused) == 2                       # k1 merged across text+ocr
    top = next(h for h in fused if h.key == "k1")
    assert set(top.contributing_modalities) == {"text", "ocr"}
    assert "text" in top.fusion_contributions and "ocr" in top.fusion_contributions
    assert fused[0].final_rank == 1


def test_weighted_sum_strategy():
    a = RetrievalHit(key="k1", modality="text", source_type="t", document_id="d", content="x", normalized_score=1.0, rank_in_modality=1)
    fused = fuse({"text": [a]}, {"text": 2.0}, strategy="weighted_sum")
    assert abs(fused[0].fusion_score - 2.0) < 1e-6   # weight × normalized_score


# ------------------------------------------------------------------ lexical scorer
def test_lexical_score_weights_fields():
    s1 = lexical_score(["deadlock"], [("cpu deadlock handling", 1.0)])
    s2 = lexical_score(["deadlock"], [("nothing here", 1.0)])
    assert s1 > 0 and s2 == 0.0
    # Higher field weight → higher score.
    assert lexical_score(["name"], [("name", 2.0)]) > lexical_score(["name"], [("name", 1.0)])


# ------------------------------------------------------------------ retrievers (DB-backed)
def _seed(db, ws="w1", owner="u1"):
    db.add(MultimodalChunk(job_id="j1", workspace_id=ws, document_id="d1", page_number=1,
                           chunk_type="ocr", source="ocr", chunk_index=0, content="the cpu scheduler prevents deadlock"))
    db.add(VisionAnalysis(job_id="j1", workspace_id=ws, document_id="d1", asset_type="figure", asset_id="fig1",
                          page_number=2, image_type="architecture_diagram", caption="System architecture with API Auth LLM",
                          keywords=["api", "auth"], structured={"kind": "diagram", "nodes": ["API", "Auth", "LLM"]}))
    db.add(VisionAnalysis(job_id="j1", workspace_id=ws, document_id="d1", asset_type="image", asset_id="img1",
                          page_number=3, image_type="general_image", caption="a photo of a cat", keywords=["cat"]))
    db.add(ExtractedTable(job_id="j1", workspace_id=ws, document_id="d1", page_number=4,
                          headers=["Name", "Score"], cells=[["Alice", "9"]], caption="Results table"))
    db.add(Document(id="d1", workspace_id=ws, owner_id=owner, vector_document_id="vd1",
                    filename="os.pdf", display_name="Operating Systems", description="A course on OS", file_type="pdf"))
    db.commit()


def _ctx(db, keywords, ws="w1", owner="u1"):
    return RetrievalContext(db=db, workspace_id=ws, owner_id=owner, query=" ".join(keywords), keywords=keywords)


def test_ocr_retriever(db_session):
    _seed(db_session)
    hits = OcrRetriever().retrieve(_ctx(db_session, ["deadlock"]), 10)
    assert len(hits) == 1 and hits[0].modality == "ocr" and "deadlock" in hits[0].content


def test_diagram_retriever(db_session):
    _seed(db_session)
    hits = DiagramRetriever().retrieve(_ctx(db_session, ["architecture"]), 10)
    assert len(hits) == 1 and hits[0].source_type == "diagram"
    # Diagram retriever ignores the general image and the table.
    assert hits[0].asset_id == "fig1"


def test_image_retriever_excludes_diagram_and_table(db_session):
    _seed(db_session)
    hits = ImageRetriever().retrieve(_ctx(db_session, ["cat"]), 10)
    assert len(hits) == 1 and hits[0].asset_id == "img1"


def test_table_retriever_header_aware(db_session):
    _seed(db_session)
    hits = TableRetriever().retrieve(_ctx(db_session, ["score"]), 10)
    assert len(hits) == 1 and hits[0].modality == "table" and hits[0].metadata["headers"] == ["Name", "Score"]


def test_metadata_retriever(db_session):
    _seed(db_session)
    hits = MetadataRetriever().retrieve(_ctx(db_session, ["operating"]), 10)
    assert len(hits) == 1 and hits[0].source_type == "document" and hits[0].document_id == "d1"


# ------------------------------------------------------------------ cross-modal rerank
def test_reranker_sets_confidence_and_ranks():
    a = RetrievalHit(key="k1", modality="diagram", source_type="diagram", document_id="d", title="architecture diagram",
                     content="system architecture", fusion_score=0.02, normalized_score=1.0)
    b = RetrievalHit(key="k2", modality="text", source_type="t", document_id="d", title="", content="unrelated text",
                     fusion_score=0.01, normalized_score=0.5)
    ranked = LexicalCrossModalReranker().rerank("architecture diagram", ["architecture", "diagram"], [a, b], primary="diagram")
    assert ranked[0].key == "k1" and ranked[0].confidence >= ranked[1].confidence
    assert all(h.final_rank for h in ranked)


def test_no_rerank_uses_fusion_confidence():
    a = RetrievalHit(key="k1", modality="text", source_type="t", document_id="d", content="x", fusion_score=0.02)
    out = no_rerank([a])
    assert out[0].confidence == 1.0
