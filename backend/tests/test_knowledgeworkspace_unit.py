"""Unit tests for the Phase-7 Module-4 graph editor + orchestrator helpers — pure/offline.

Covers controlled editing (rename/merge/split/delete/create/review) with versioning + soft-delete over
an in-memory graph, plus the analytics + timeline aggregators.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.documents.models  # noqa: F401
import app.graphreason.models  # noqa: F401
import app.ingestion.models  # noqa: F401
import app.knowledge.models  # noqa: F401
import app.knowledgeworkspace.models  # noqa: F401
import app.media.models  # noqa: F401
import app.memory.models  # noqa: F401
import app.reasoning.models  # noqa: F401
import app.workspaces.models  # noqa: F401

from app.knowledge.models import GraphRelationship
from app.knowledge.repository import GraphRepository
from app.knowledge.service import KnowledgeGraphService
from app.knowledgeworkspace.editing import GraphEditor
from app.knowledgeworkspace.errors import EntityNotFound, InvalidEdit
from app.knowledgeworkspace.analytics import graph_analytics
from app.knowledgeworkspace.timeline import knowledge_timeline


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    KnowledgeGraphService(GraphRepository(s)).build_text(
        "o", "ws", "React uses JavaScript. React depends on Node.js. JavaScript depends on Node.js.")
    yield s
    s.close()


def _ent(db, name):
    return next(e for e in GraphRepository(db).workspace_entities("ws", "o") if e.canonical_name == name)


# --------------------------------------------------------------------- rename
def test_rename_keeps_old_name_as_alias_and_bumps_version(db):
    react = _ent(db, "React")
    ed = GraphEditor(db)
    out = ed.rename_entity(react.id, "o", new_name="React.js")
    assert out.canonical_name == "React.js" and "React" in out.aliases
    assert out.normalized_name == "reactjs" and out.version == 2


def test_rename_rejects_invalid_name(db):
    react = _ent(db, "React")
    try:
        GraphEditor(db).rename_entity(react.id, "o", new_name="")
        assert False
    except InvalidEdit:
        pass


# --------------------------------------------------------------------- merge
def test_merge_repoints_edges_and_soft_deletes_source(db):
    react = _ent(db, "React"); js = _ent(db, "JavaScript")
    ed = GraphEditor(db)
    target = ed.merge_entities(js.id, react.id, "o")   # merge JavaScript into React
    assert target.canonical_name == "React" and "JavaScript" in target.aliases
    merged = GraphRepository(db).get_entity(js.id, "o")
    assert merged.status == "merged" and merged.merged_into == react.id
    # JavaScript no longer appears in the active graph
    active = {e.canonical_name for e in GraphRepository(db).workspace_entities("ws", "o")}
    assert "JavaScript" not in active


# --------------------------------------------------------------------- split / delete / create
def test_split_creates_new_entity(db):
    react = _ent(db, "React")
    new = GraphEditor(db).split_entity(react.id, "o", new_name="React Native")
    assert new.canonical_name == "React Native" and new.id != react.id and new.status == "active"


def test_delete_entity_soft_deletes_and_drops_edges(db):
    node = _ent(db, "Node.js")
    GraphEditor(db).delete_entity(node.id, "o")
    active = {e.canonical_name for e in GraphRepository(db).workspace_entities("ws", "o")}
    assert "Node.js" not in active


def test_create_and_delete_relationship(db):
    react = _ent(db, "React"); node = _ent(db, "Node.js")
    ed = GraphEditor(db)
    rel = ed.create_relationship("ws", "o", source_id=react.id, target_id=node.id, rel_type="implements")
    assert rel.status == "active" and rel.rel_type == "implements"
    deleted = ed.delete_relationship(rel.id, "o")
    assert deleted.status == "deleted" and deleted.deleted_at is not None


def test_create_relationship_rejects_bad_type(db):
    react = _ent(db, "React"); node = _ent(db, "Node.js")
    try:
        GraphEditor(db).create_relationship("ws", "o", source_id=react.id, target_id=node.id, rel_type="pwns")
        assert False
    except InvalidEdit:
        pass


# --------------------------------------------------------------------- review inferred
def test_approve_inferred_relationship(db):
    react = _ent(db, "React"); node = _ent(db, "Node.js")
    # manufacture an inferred edge
    from app.knowledge.models import GraphRelationship as GR
    import uuid
    r = GR(id=f"rel_{uuid.uuid4().hex[:12]}", workspace_id="ws", owner_id="o", source_id=react.id,
           target_id=node.id, rel_type="depends_on", status="inferred", confidence=0.5, version=1)
    db.add(r); db.commit()
    approved = GraphEditor(db).review_inferred(r.id, "o", approve=True)
    assert approved.status == "active" and approved.confidence > 0.5


def test_review_rejects_non_inferred(db):
    r = db.scalar(select(GraphRelationship).where(GraphRelationship.status == "active"))
    try:
        GraphEditor(db).review_inferred(r.id, "o", approve=True)
        assert False
    except InvalidEdit:
        pass


# --------------------------------------------------------------------- analytics + timeline
def test_analytics_and_timeline(db):
    a = graph_analytics(db, "ws", "o")
    assert a["entities"] >= 3 and a["top_connected"] and "growth" in a
    tl = knowledge_timeline(db, "ws", "o")
    assert tl and any(e["type"] == "entity_created" for e in tl)
