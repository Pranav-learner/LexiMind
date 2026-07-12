"""Unit tests for the Phase-7 Module-1 Knowledge Graph engine — pure/offline (no HTTP, no LLM).

Covers normalization, the gazetteer, entity + relationship extraction, resolution/dedup, the validator,
and the full builder (extract → resolve → dedup → version → store → validate) over an in-memory DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
# register the models used by these tests
import app.documents.models  # noqa: F401
import app.ingestion.models  # noqa: F401
import app.knowledge.models  # noqa: F401
import app.media.models  # noqa: F401
import app.workspaces.models  # noqa: F401

from app.knowledge import gazetteer
from app.knowledge.builder import GraphBuilder
from app.knowledge.extraction import EntityExtractor, RelationshipExtractor
from app.knowledge.models import GraphEntity, GraphRelationship
from app.knowledge.repository import GraphRepository
from app.knowledge.resolution import GraphResolver
from app.knowledge.sources import TextSource
from app.knowledge.validation import normalize_name
from app.knowledge.validator import GraphValidator


# --------------------------------------------------------------------- normalization + gazetteer
def test_normalize_name():
    assert normalize_name("Node.js") == normalize_name("NodeJS") == normalize_name("node js") == "nodejs"


def test_gazetteer_resolves_aliases():
    assert gazetteer.resolve("LLM") == ("Large Language Model", "concept")
    assert gazetteer.resolve("nodejs")[0] == "Node.js"
    assert gazetteer.resolve("unknownthing") is None


def test_classify_cue():
    assert gazetteer.classify_cue(" depends on ") == "depends_on"
    assert gazetteer.classify_cue(" was created by ") == "created_by"
    assert gazetteer.classify_cue(" and ") == "related_to"


# --------------------------------------------------------------------- entity extraction
def test_entity_extraction_gazetteer_acronym_proper():
    txt = ("React uses JavaScript. A Large Language Model (LLM) depends on PyTorch. "
           "The Kubernetes Foundation maintains it.")
    ents = {e.canonical_name: e for e in EntityExtractor().extract(txt, {"document_id": "d1"})}
    assert "React" in ents and ents["React"].entity_type == "framework"
    assert "Large Language Model" in ents and "LLM" in ents["Large Language Model"].aliases
    assert ents["Large Language Model"].confidence >= 0.85
    assert any(e.entity_type == "organization" for e in ents.values())   # Kubernetes Foundation


def test_entity_extraction_no_cross_sentence_false_positives():
    txt = "Node.js was created by Ryan Dahl. FAISS implements search."
    names = {e.canonical_name for e in EntityExtractor().extract(txt, {})}
    assert "Node.js" in names and "FAISS" in names
    assert not any("Dahl. FAISS" in n or "Node.js" in n and "FAISS" in n for n in names)


# --------------------------------------------------------------------- relationship extraction
def test_relationship_extraction_typed_and_directed():
    txt = "React uses JavaScript. Large Language Model depends on PyTorch."
    ents = EntityExtractor().extract(txt, {})
    rels = {(r.source_name, r.rel_type, r.target_name) for r in RelationshipExtractor().extract(txt, ents, {})}
    assert ("React", "uses", "JavaScript") in rels
    assert ("Large Language Model", "depends_on", "PyTorch") in rels


# --------------------------------------------------------------------- resolution / dedup
def test_resolver_matches_by_alias():
    e = GraphEntity(id="ent_1", workspace_id="ws", owner_id="o", entity_type="concept",
                    canonical_name="Large Language Model", normalized_name="largelanguagemodel",
                    aliases=["LLM"])
    resolver = GraphResolver([e])
    from app.knowledge.extraction import ExtractedEntity
    assert resolver.match(ExtractedEntity(canonical_name="LLM", entity_type="concept")) is e
    assert resolver.match(ExtractedEntity(canonical_name="Something Else", entity_type="concept")) is None


# --------------------------------------------------------------------- validator
def test_validator_flags_broken_and_selfloop_and_orphan():
    ents = [GraphEntity(id="a", workspace_id="w", owner_id="o", entity_type="concept",
                        canonical_name="A", normalized_name="a", status="active"),
            GraphEntity(id="b", workspace_id="w", owner_id="o", entity_type="concept",
                        canonical_name="B", normalized_name="b", status="active")]
    rels = [
        GraphRelationship(id="r1", workspace_id="w", owner_id="o", source_id="a", target_id="ghost",
                          rel_type="uses", status="active"),          # broken endpoint
        GraphRelationship(id="r2", workspace_id="w", owner_id="o", source_id="a", target_id="a",
                          rel_type="depends_on", status="active"),    # invalid self-loop
    ]
    report = GraphValidator().validate(ents, rels)
    kinds = {e["kind"] for e in report.errors}
    assert "broken_relationship" in kinds and "invalid_self_loop" in kinds and report.ok is False
    assert any(w["kind"] == "orphan_nodes" for w in report.warnings)   # B has no edges


# --------------------------------------------------------------------- builder (full pipeline over DB)
@pytest.fixture()
def store():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    yield GraphRepository(db)
    db.close()


def test_builder_incremental_merge_and_versioning(store):
    b = GraphBuilder(store)
    r1 = b.build("ws", "o", [TextSource("React is built on JavaScript. A Large Language Model (LLM) "
                                        "depends on PyTorch.", {"document_id": "d1"})])
    assert r1.entities_created == 4 and r1.relationships_created >= 2 and r1.report["ok"]

    # second build: "LLM" + "PyTorch" merge into existing canonicals; GPT/OpenAI are new
    r2 = b.build("ws", "o", [TextSource("GPT is a Large Language Model developed by OpenAI. LLM uses PyTorch.",
                                        {"document_id": "d2"})])
    assert r2.entities_created == 2 and r2.entities_merged >= 1 and r2.duplicates_merged >= 1

    llm = next(e for e in store.workspace_entities("ws", "o") if e.canonical_name == "Large Language Model")
    assert llm.mention_count >= 2 and llm.version >= 2 and len(llm.source_refs) >= 2   # provenance + version
    assert store.metrics("ws")["entities"] == 6


def test_builder_dedupes_across_normalization(store):
    b = GraphBuilder(store)
    b.build("ws", "o", [TextSource("We use Node.js here.", {"document_id": "d1"})])
    b.build("ws", "o", [TextSource("NodeJS and node js are great.", {"document_id": "d2"})])
    nodes = [e for e in store.workspace_entities("ws", "o") if e.canonical_name == "Node.js"]
    assert len(nodes) == 1 and nodes[0].mention_count >= 2   # one canonical node despite spelling variants
