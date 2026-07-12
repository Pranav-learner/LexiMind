"""Unit tests for the Phase-7 Module-3 Graph Reasoning engine — pure/offline (no HTTP, no LLM).

Covers path enumeration, relationship inference (transitive rules), confidence propagation, dependency/
root-cause analysis, the explanation builder, the reasoning cache, and the full reasoner over a graph.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.documents.models  # noqa: F401
import app.graphreason.models  # noqa: F401
import app.ingestion.models  # noqa: F401
import app.knowledge.models  # noqa: F401
import app.media.models  # noqa: F401
import app.memory.models  # noqa: F401
import app.reasoning.models  # noqa: F401
import app.workspaces.models  # noqa: F401

from app.graphreason.cache import ReasoningCache
from app.graphreason.confidence import ConfidencePropagation, WEIGHTS
from app.graphreason.dependency import DependencyAnalyzer
from app.graphreason.engine import GraphReasoner
from app.graphreason.explanation import ExplanationBuilder
from app.graphreason.inference import RelationshipInference, _reduce_chain
from app.graphreason.interfaces import PathEdge, ReasoningPath
from app.graphreason.paths import PathReasoner, build_adjacency
from app.knowledge.repository import GraphRepository
from app.knowledge.service import KnowledgeGraphService


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    KnowledgeGraphService(GraphRepository(s)).build_text(
        "o", "ws",
        "Paging is part of Virtual Memory. Virtual Memory is part of Memory Management. "
        "Memory Management is part of the Operating System. React uses JavaScript. "
        "JavaScript depends on Node.js. FastAPI depends on Pydantic. FastAPI uses Python.")
    yield s
    s.close()


def _adj(db, directed=False):
    repo = GraphRepository(db)
    ents = {e.id: e for e in repo.workspace_entities("ws", "o")}
    edges = repo.workspace_relationships("ws", "o")
    return build_adjacency(edges, ents, directed=directed), ents


# --------------------------------------------------------------------- paths
def test_multi_hop_paths(db):
    adj, ents = _adj(db)
    os_id = next(e.id for e in ents.values() if e.canonical_name == "Operating System")
    paths = PathReasoner().find_paths(adj, ents, [os_id], hops=3)
    assert paths and any(p.length >= 2 for p in paths)          # a 2-hop chain exists
    longest = max(paths, key=lambda p: p.length)
    assert "Memory Management" in longest.node_names


def test_path_cycle_protection_and_cap(db):
    adj, ents = _adj(db)
    os_id = next(e.id for e in ents.values() if e.canonical_name == "Operating System")
    paths = PathReasoner().find_paths(adj, ents, [os_id], hops=5, max_paths=2)
    assert len(paths) <= 2
    for p in paths:
        assert len(p.node_ids) == len(set(p.node_ids))          # no repeated node (cycle-free)


# --------------------------------------------------------------------- inference
def test_reduce_chain_transitive():
    assert _reduce_chain(["part_of", "part_of"]) == "part_of"
    assert _reduce_chain(["uses", "depends_on"]) == "depends_on"
    assert _reduce_chain(["created_by", "uses"]) is None        # doesn't compose


def test_relationship_inference(db):
    adj, ents = _adj(db)
    os_id = next(e.id for e in ents.values() if e.canonical_name == "Operating System")
    paths = PathReasoner().find_paths(adj, ents, [os_id], hops=3)
    inferences = RelationshipInference().infer(paths)
    assert any(r.source_name == "Operating System" and r.target_name == "Virtual Memory"
               and r.rel_type == "part_of" for r in inferences)
    assert all(r.hops >= 2 for r in inferences)                 # inferences are multi-hop only


# --------------------------------------------------------------------- confidence
def test_confidence_weights_and_propagation():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    edge = PathEdge(rel_id="r1", rel_type="part_of", source_id="a", target_id="b", source_name="A",
                    target_name="B", weight=0.8, confidence=0.9, evidence=[{"text": "x"}])
    path = ReasoningPath(node_ids=["a", "b"], node_names=["A", "B"], edges=[edge], path_confidence=0.8)
    pc = ConfidencePropagation().propagate([path], [], node_index={}, signals_in={"seed_count": 1})
    assert 0.0 <= pc.overall <= 1.0 and pc.breakdown.band in ("high", "moderate", "low")
    assert "r1" in pc.edge_confidence and pc.path_confidence == [0.8]


# --------------------------------------------------------------------- dependency / root cause
def test_dependency_root_cause(db):
    adj_dir, ents = _adj(db, directed=True)
    react_id = next(e.id for e in ents.values() if e.canonical_name == "React")
    chains, root_causes = DependencyAnalyzer().analyze(adj_dir, ents, react_id)
    assert chains and any(c.is_root_cause for c in chains)
    # React uses JavaScript, JavaScript depends_on Node.js → Node.js is the terminal dependency
    assert any(rc["entity"] == "Node.js" for rc in root_causes)


# --------------------------------------------------------------------- explanation (no chain-of-thought)
def test_explanation_is_structured(db):
    reasoner = GraphReasoner(db)
    result = reasoner.reason("ws", "o", query="how does Operating System relate to Virtual Memory", hops=3)
    ex = ExplanationBuilder().build(result)
    assert {"reasoning_pipeline", "reasoning_paths", "relationship_chains", "confidence",
            "why_conclusion"} <= set(ex.keys())
    assert isinstance(ex["reasoning_pipeline"], list) and "chain-of-thought" not in str(ex).lower()


# --------------------------------------------------------------------- cache
def test_reasoning_cache():
    c = ReasoningCache(capacity=2)
    assert c.get("ws", ["a"], 3, False) is None and c.misses == 1
    c.put("ws", ["a"], 3, False, object())
    assert c.get("ws", ["a"], 3, False) is not None and c.hits == 1
    assert c.invalidate_workspace("ws") == 1 and c.get("ws", ["a"], 3, False) is None


# --------------------------------------------------------------------- full reasoner
def test_reasoner_full_run(db):
    result = GraphReasoner(db).reason("ws", "o", query="operating system memory", hops=4)
    assert result.seeds and result.paths and result.confidence is not None
    assert result.verification and result.verification["graph_consistency"] is True
    assert result.context_text and result.explanation
    assert result.complexity["paths"] == len(result.paths)
