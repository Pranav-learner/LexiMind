"""Unit tests for the Phase-7 Module-2 Semantic Memory & Graph Retrieval — pure/offline (no HTTP, no LLM).

Covers entity recognition, traversal (BFS/DFS/N-hop/cycle/filter/cap), the graph retrievers, memory
scoring, the neighborhood cache, hybrid fusion (reusing Phase-4 fuse), and graph-aware context assembly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.documents.models  # noqa: F401
import app.ingestion.models  # noqa: F401
import app.knowledge.models  # noqa: F401
import app.media.models  # noqa: F401
import app.memory.models  # noqa: F401
import app.workspaces.models  # noqa: F401

from app.knowledge.repository import GraphRepository
from app.knowledge.service import KnowledgeGraphService
from app.memory.cache import NeighborhoodCache
from app.memory.context import build_graph_context
from app.memory.fusion import hybrid_fuse
from app.memory.interfaces import GraphHit, Neighborhood
from app.memory.recognition import QueryEntityRecognizer
from app.memory.retrievers import ALL_RETRIEVERS, RetrieverContext
from app.memory.scoring import MemoryScorer, WEIGHTS
from app.memory.traversal import TraversalEngine


@pytest.fixture()
def graph():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    KnowledgeGraphService(GraphRepository(db)).build_text(
        "o", "ws",
        "React is built on JavaScript and uses a virtual DOM. React depends on Node.js. "
        "A Large Language Model (LLM) depends on PyTorch. GPT is a Large Language Model developed by OpenAI.")
    yield GraphRepository(db)
    db.close()


# --------------------------------------------------------------------- recognition
def test_query_entity_recognition(graph):
    seeds = QueryEntityRecognizer().recognize("explain how React and Node.js work", "ws", "o", repo=graph)
    names = {s.canonical_name for s in seeds}
    assert "React" in names and "Node.js" in names


def test_recognition_falls_back_to_keyword_search(graph):
    # no gazetteer/acronym hit → keyword fallback still finds a named node
    seeds = QueryEntityRecognizer().recognize("tell me about javascript", "ws", "o", repo=graph)
    assert any(s.canonical_name == "JavaScript" for s in seeds)


# --------------------------------------------------------------------- traversal
def test_traversal_bfs_hop_distances(graph):
    react = next(e for e in graph.workspace_entities("ws", "o") if e.canonical_name == "React")
    nb = TraversalEngine().expand(graph, "ws", "o", [react.id], hops=1)
    assert nb.hop[react.id] == 0
    neighbors = {e.canonical_name for nid, e in nb.nodes.items() if nb.hop[nid] == 1}
    assert {"JavaScript", "Node.js"} <= neighbors     # 1-hop neighbours of React


def test_traversal_relationship_filter_and_cap(graph):
    react = next(e for e in graph.workspace_entities("ws", "o") if e.canonical_name == "React")
    only_deps = TraversalEngine().expand(graph, "ws", "o", [react.id], hops=2, rel_types=["depends_on"])
    assert any(e.canonical_name == "Node.js" for e in only_deps.nodes.values())
    capped = TraversalEngine().expand(graph, "ws", "o", [react.id], hops=3, max_nodes=1)
    assert capped.truncated is True and capped.size <= 1


def test_traversal_no_seeds_is_empty(graph):
    nb = TraversalEngine().expand(graph, "ws", "o", [], hops=2)
    assert nb.size == 0 and nb.edges == []


# --------------------------------------------------------------------- retrievers + scoring
def test_retrievers_produce_typed_hits(graph):
    react = next(e for e in graph.workspace_entities("ws", "o") if e.canonical_name == "React")
    nb = TraversalEngine().expand(graph, "ws", "o", [react.id], hops=2)
    ctx = RetrieverContext(query="react", seeds=[react], neighborhood=nb)
    kinds = set()
    for r in ALL_RETRIEVERS:
        for h in r.retrieve(ctx):
            kinds.add(h.kind)
    assert {"entity", "neighbor", "relationship"} <= kinds


def test_memory_scorer_is_explainable():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    hit = GraphHit(kind="relationship", key="rel:1", text="A —uses→ B", hop_distance=1, base_score=0.7,
                   signals={"rel_weight": 0.8, "rel_confidence": 0.9}, provenance=[{"text": "x"}])
    MemoryScorer().score(hit)
    assert 0.0 <= hit.score <= 1.0
    assert "sig_base_relevance" in hit.signals and "sig_distance_decay" in hit.signals


def test_closer_hop_scores_higher():
    near = GraphHit(kind="neighbor", key="ent:1", text="A", hop_distance=1, base_score=0.6)
    far = GraphHit(kind="neighbor", key="ent:2", text="B", hop_distance=3, base_score=0.6)
    MemoryScorer().score(near); MemoryScorer().score(far)
    assert near.score > far.score


# --------------------------------------------------------------------- cache
def test_neighborhood_cache_hit_miss():
    c = NeighborhoodCache(capacity=2)
    assert c.get("ws", ["a"], 2, "bfs", None) is None and c.misses == 1
    c.put("ws", ["a"], 2, "bfs", None, Neighborhood(seeds=["a"]))
    assert c.get("ws", ["a"], 2, "bfs", None) is not None and c.hits == 1
    assert c.invalidate_workspace("ws") == 1 and c.get("ws", ["a"], 2, "bfs", None) is None


# --------------------------------------------------------------------- fusion (reuses Phase-4 fuse)
def test_hybrid_fuse_ranks_graph_and_vectors():
    graph_hits = [GraphHit(kind="entity", key="ent:1", text="React", base_score=0.9, score=0.9),
                  GraphHit(kind="relationship", key="rel:1", text="A uses B", base_score=0.6, score=0.6)]
    from app.mmretrieval.schemas import RetrievalHit
    vec = [RetrievalHit(key="chunk:1", modality="text", source_type="text_chunk", document_id="d1",
                        content="react is a library", normalized_score=0.8, rank_in_modality=1)]
    fused = hybrid_fuse(graph_hits, vec)
    assert len(fused) == 3
    assert {h.modality for h in fused} == {"graph", "text"}
    assert fused[0].fusion_score >= fused[-1].fusion_score       # ranked


def test_hybrid_fuse_graph_only():
    graph_hits = [GraphHit(kind="entity", key="ent:1", text="React", score=0.9)]
    fused = hybrid_fuse(graph_hits, [])
    assert len(fused) == 1 and fused[0].modality == "graph"


# --------------------------------------------------------------------- context
def test_graph_context_dedupes_and_cites():
    hits = [GraphHit(kind="entity", key="ent:1", text="React (framework)", score=0.9),
            GraphHit(kind="concept", key="ent:1", text="React", score=0.5),   # same key → dedup
            GraphHit(kind="relationship", key="rel:1", text="React —uses→ JS", score=0.7)]
    ctx = build_graph_context(hits, limit=10)
    assert ctx["entity_count"] == 1 and ctx["relationship_count"] == 1
    assert len(ctx["citations"]) == 2 and "Concepts:" in ctx["context_text"]
    assert "[1]" in ctx["context_text"]
