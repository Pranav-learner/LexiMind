"""Unit tests for the multimodal context pipeline stages (pure, no faiss/torch/LLM)."""

from __future__ import annotations

from app.mmcontext import assembly, budget, citations, compression, dedup, prompt, ranking
from app.mmcontext.schemas import MMEvidence


def _ev(key, modality, content, score=0.8, doc="d", page=1, **kw):
    return MMEvidence(key=key, modality=modality, source_type=modality, content=content,
                      base_score=score, document_id=doc, page_number=page, **kw)


# ------------------------------------------------------------------ cross-modal dedup
def test_dedup_merges_text_and_ocr_duplicate():
    a = _ev("c1", "text", "the cpu scheduler prevents deadlock in the kernel", 0.9)
    b = _ev("c2", "ocr", "the cpu scheduler prevents deadlock in the kernel", 0.7)   # same content, other modality
    c = _ev("a1", "diagram", "architecture diagram of api auth and llm services", 0.8)  # complementary
    kept, removed = dedup.deduplicate([a, b, c])
    assert removed == 1 and len(kept) == 2
    rep = next(e for e in kept if e.modality == "text")   # strongest kept as representative
    assert "ocr" in rep.contributing_modalities and "c2" in rep.merged_from


def test_dedup_keeps_complementary_evidence():
    a = _ev("c1", "text", "deadlock happens when processes wait circularly", 0.9)
    b = _ev("c2", "text", "banker's algorithm avoids deadlock via safe states", 0.8)  # different content
    kept, removed = dedup.deduplicate([a, b])
    assert removed == 0 and len(kept) == 2


# ------------------------------------------------------------------ cross-modal ranking
def test_ranking_blends_signals_and_explains():
    a = _ev("c1", "diagram", "system architecture", 0.9, vision_confidence=0.95)
    ranked = ranking.rank([a], {"diagram": 1.35, "text": 1.0})
    assert 0 < a.evidence_score <= 1
    # Every signal recorded a weighted contribution (explainability).
    assert set(a.ranking_contributions) == set(ranking.WEIGHTS)
    assert abs(sum(a.ranking_contributions.values()) - a.evidence_score) < 1e-4


def test_ranking_modality_importance_boosts():
    a = _ev("c1", "diagram", "architecture", 0.6)
    b = _ev("c2", "metadata", "architecture", 0.6)
    ranking.rank([a, b], {"diagram": 1.35, "metadata": 0.5})
    assert a.evidence_score > b.evidence_score   # diagram up-weighted for a diagram-intent query


# ------------------------------------------------------------------ adaptive budget
def test_budget_respects_total_and_allocations():
    items = [_ev(f"c{i}", "text", "word " * 50, 0.9 - i * 0.1) for i in range(5)]
    ranking.rank(items, {"text": 1.0})
    included, dropped, used = budget.manage(items, {"text": 1.0}, 60, compress=False)
    assert sum(e.token_cost for e in included) <= 60          # hard ceiling never exceeded
    assert len(included) + len(dropped) == 5


def test_budget_compresses_to_fit():
    big = _ev("c1", "text", ". ".join(f"sentence number {i} about deadlock" for i in range(40)), 0.9)
    ranking.rank([big], {"text": 1.0})
    inc, _dropped, _used = budget.manage([big], {"text": 1.0}, 40, compress=True,
                                         compress_fn=lambda ev, lim: compression.compress(ev.content, ev.modality, lim, ["deadlock"], {}))
    assert inc and inc[0].compressed and inc[0].token_cost <= 40


def test_budget_allocates_by_intent_weight():
    alloc = budget.allocate({"diagram": 1.35, "text": 1.0}, ["diagram", "text"], 1000)
    assert alloc["diagram"] > alloc["text"]                    # diagram intent gets more budget


# ------------------------------------------------------------------ compression
def test_compression_table_summarizes():
    out = compression.compress("a very long table serialization " * 30, "table", 20, [], {"headers": ["A", "B"], "n_rows": 5})
    assert "columns" in out and "5 rows" in out


def test_ocr_cleanup_joins_hyphenation():
    assert compression.ocr_cleanup("hyphen-\nated  word") == "hyphenated word"


# ------------------------------------------------------------------ adaptive assembly
def test_assembly_orders_primary_first():
    a = _ev("c1", "text", "text", 0.9); a.included = True; a.rank = 2
    b = _ev("a1", "diagram", "diagram", 0.8); b.included = True; b.rank = 1
    blocks = assembly.assemble([a, b], {"diagram": 1.35, "text": 1.0}, "diagram")
    assert [blk.modality for blk in blocks] == ["diagram", "text"]


# ------------------------------------------------------------------ prompt builder
def test_prompt_is_deterministic_and_cited():
    a = _ev("c1", "text", "deadlock explanation", 0.9); a.included = True; a.rank = 1; a.token_cost = 5
    blocks = assembly.assemble([a], {"text": 1.0}, "text")
    p1, ctx1, idx1 = prompt.build("what is deadlock?", blocks)
    p2, _c2, _i2 = prompt.build("what is deadlock?", blocks)
    assert p1 == p2                                            # deterministic
    assert "[1]" in ctx1 and idx1[0]["index"] == 1 and "LexiMind" in p1


# ------------------------------------------------------------------ citations
def test_citation_manager_dedups_targets():
    a = _ev("c1", "text", "x", 0.9); a.included = True; a.rank = 1
    b = _ev("c1", "text", "x", 0.9); b.included = True; b.rank = 2   # same target
    blocks = assembly.assemble([a, b], {"text": 1.0}, "text")
    cits = citations.collect(blocks)
    assert len(cits) == 1
