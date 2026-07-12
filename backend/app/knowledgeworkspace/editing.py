"""Controlled Graph Editing (Step 11) — human-in-the-loop curation over the Module-1 graph rows.

Every edit mutates the existing `GraphEntity`/`GraphRelationship` rows with a monotonic `version` bump +
soft-delete (never a hard delete), so history is preserved and future enterprise approval workflows plug
in at this seam. Operations: rename · merge · split · edit-metadata · create/delete relationship ·
approve/reject an AI-inferred relationship (status `inferred` → `active`/`deleted`). Structural edits
recompute node degree. No new graph logic — it reuses the Module-1 `GraphRepository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.knowledge.models import GraphEntity, GraphRelationship
from app.knowledge.repository import GraphRepository
from app.knowledge.validation import normalize_name, valid_entity_name
from app.knowledgeworkspace.errors import EntityNotFound, InvalidEdit, RelationshipNotFound


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GraphEditor:
    def __init__(self, db: Session):
        self.db = db
        self.repo = GraphRepository(db)

    # ------------------------------------------------------------------ helpers
    def _entity(self, entity_id: str, owner_id: str) -> GraphEntity:
        e = self.repo.get_entity(entity_id, owner_id)
        if e is None or e.status == "deleted":
            raise EntityNotFound(entity_id)
        return e

    def _relationship(self, rel_id: str, owner_id: str) -> GraphRelationship:
        r = self.db.scalar(select(GraphRelationship).where(
            GraphRelationship.id == rel_id, GraphRelationship.owner_id == owner_id))
        if r is None or r.status == "deleted":
            raise RelationshipNotFound(rel_id)
        return r

    # ------------------------------------------------------------------ entity edits
    def rename_entity(self, entity_id: str, owner_id: str, *, new_name: str) -> GraphEntity:
        if not valid_entity_name(new_name):
            raise InvalidEdit("The new entity name is invalid.")
        e = self._entity(entity_id, owner_id)
        old = e.canonical_name
        if old and old != new_name:
            aliases = list(e.aliases or [])
            if old not in aliases:
                aliases.append(old)          # keep the old name as an alias
            e.aliases = aliases[:50]
        e.canonical_name = new_name
        e.normalized_name = normalize_name(new_name)
        e.version += 1
        self.repo.update_entity(e); self.db.commit(); self.db.refresh(e)
        return e

    def edit_metadata(self, entity_id: str, owner_id: str, *, description: Optional[str] = None,
                      entity_type: Optional[str] = None, aliases: Optional[List[str]] = None) -> GraphEntity:
        e = self._entity(entity_id, owner_id)
        if description is not None:
            e.description = description[:4000]
        if entity_type is not None:
            from app.knowledge.validation import is_valid_entity_type
            if not is_valid_entity_type(entity_type):
                raise InvalidEdit(f"'{entity_type}' is not a valid entity type.")
            e.entity_type = entity_type
        if aliases is not None:
            e.aliases = list(dict.fromkeys(a for a in aliases if a))[:50]
        e.version += 1
        self.repo.update_entity(e); self.db.commit(); self.db.refresh(e)
        return e

    def merge_entities(self, source_id: str, target_id: str, owner_id: str) -> GraphEntity:
        if source_id == target_id:
            raise InvalidEdit("Cannot merge an entity into itself.")
        source = self._entity(source_id, owner_id)
        target = self._entity(target_id, owner_id)
        if source.workspace_id != target.workspace_id:
            raise InvalidEdit("Entities are in different workspaces.")

        # fold source aliases/name + provenance into target
        aliases = list(target.aliases or [])
        for a in [source.canonical_name, *(source.aliases or [])]:
            if a and normalize_name(a) != target.normalized_name and a not in aliases:
                aliases.append(a)
        target.aliases = aliases[:50]
        refs = list(target.source_refs or []) + list(source.source_refs or [])
        target.source_refs = refs[-25:]
        target.mention_count = (target.mention_count or 0) + (source.mention_count or 0)
        target.confidence = max(target.confidence, source.confidence)
        target.version += 1

        # repoint edges from source → target, dropping self-loops + duplicates
        edges = self.db.scalars(select(GraphRelationship).where(
            GraphRelationship.workspace_id == source.workspace_id,
            or_(GraphRelationship.source_id == source_id, GraphRelationship.target_id == source_id))).all()
        for r in edges:
            if r.source_id == source_id:
                r.source_id = target_id
            if r.target_id == source_id:
                r.target_id = target_id
            if r.source_id == r.target_id:            # self-loop created by the merge
                r.status = "deleted"; r.deleted_at = _now()
            r.version += 1

        source.status = "merged"; source.merged_into = target_id; source.deleted_at = _now()
        source.version += 1
        self.repo.update_entity(target); self.repo.update_entity(source)
        self.db.commit()
        self._recompute_degrees(source.workspace_id, owner_id)
        self.db.commit(); self.db.refresh(target)
        return target

    def split_entity(self, entity_id: str, owner_id: str, *, new_name: str,
                     move_aliases: Optional[List[str]] = None) -> GraphEntity:
        if not valid_entity_name(new_name):
            raise InvalidEdit("The new entity name is invalid.")
        src = self._entity(entity_id, owner_id)
        move = set(a for a in (move_aliases or []))
        kept = [a for a in (src.aliases or []) if a not in move]
        src.aliases = kept; src.version += 1
        new = GraphEntity(
            id=f"ent_{uuid.uuid4().hex[:16]}", workspace_id=src.workspace_id, owner_id=owner_id,
            entity_type=src.entity_type, canonical_name=new_name, normalized_name=normalize_name(new_name),
            aliases=[a for a in (move_aliases or [])][:50], confidence=src.confidence, mention_count=1,
            source_refs=list(src.source_refs or [])[:5], status="active", version=1)
        self.repo.add_entity(new); self.repo.update_entity(src)
        self.db.commit(); self.db.refresh(new)
        return new

    def delete_entity(self, entity_id: str, owner_id: str) -> GraphEntity:
        e = self._entity(entity_id, owner_id)
        e.status = "deleted"; e.deleted_at = _now(); e.version += 1
        # soft-delete its edges too
        for r in self.repo.relationships_for(e.workspace_id, entity_id):
            r.status = "deleted"; r.deleted_at = _now(); r.version += 1
        self.repo.update_entity(e); self.db.commit()
        self._recompute_degrees(e.workspace_id, owner_id); self.db.commit()
        return e

    # ------------------------------------------------------------------ relationship edits
    def create_relationship(self, workspace_id: str, owner_id: str, *, source_id: str, target_id: str,
                            rel_type: str, weight: float = 1.0) -> GraphRelationship:
        from app.knowledge.validation import is_valid_relationship_type
        if source_id == target_id:
            raise InvalidEdit("A relationship needs two distinct entities.")
        if not is_valid_relationship_type(rel_type):
            raise InvalidEdit(f"'{rel_type}' is not a valid relationship type.")
        self._entity(source_id, owner_id); self._entity(target_id, owner_id)
        existing = self.repo.find_relationship(workspace_id, source_id, target_id, rel_type)
        if existing is not None:
            return existing
        rel = GraphRelationship(
            id=f"rel_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
            source_id=source_id, target_id=target_id, rel_type=rel_type, directed=True,
            weight=weight, confidence=1.0, mention_count=1,
            evidence=[{"created_by": "user"}], status="active", version=1)
        self.repo.add_relationship(rel); self.db.commit()
        self._recompute_degrees(workspace_id, owner_id); self.db.commit(); self.db.refresh(rel)
        return rel

    def delete_relationship(self, rel_id: str, owner_id: str) -> GraphRelationship:
        r = self._relationship(rel_id, owner_id)
        r.status = "deleted"; r.deleted_at = _now(); r.version += 1
        self.repo.update_relationship(r); self.db.commit()
        self._recompute_degrees(r.workspace_id, owner_id); self.db.commit()
        return r

    def review_inferred(self, rel_id: str, owner_id: str, *, approve: bool) -> GraphRelationship:
        r = self._relationship(rel_id, owner_id)
        if r.status != "inferred":
            raise InvalidEdit("Only AI-inferred relationships can be approved/rejected.")
        if approve:
            r.status = "active"; r.confidence = min(1.0, r.confidence + 0.1)
        else:
            r.status = "deleted"; r.deleted_at = _now()
        r.version += 1
        self.repo.update_relationship(r); self.db.commit()
        self._recompute_degrees(r.workspace_id, owner_id); self.db.commit()
        return r

    # ------------------------------------------------------------------ maintenance
    def _recompute_degrees(self, workspace_id: str, owner_id: str) -> None:
        entities = self.repo.workspace_entities(workspace_id, owner_id)
        rels = self.repo.workspace_relationships(workspace_id, owner_id, limit=10000)
        degree: Dict[str, int] = {}
        for r in rels:
            degree[r.source_id] = degree.get(r.source_id, 0) + 1
            degree[r.target_id] = degree.get(r.target_id, 0) + 1
        for e in entities:
            d = degree.get(e.id, 0)
            if e.degree != d:
                e.degree = d
                self.repo.update_entity(e)
