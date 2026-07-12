"""Golden Dataset Manager (Step 3) — create / import / export / version / validate datasets.

A dataset is a versioned set of golden items (question + ground truth + relevant chunks/entities +
expected citations + difficulty). Import/export is plain JSON (portable, crowd-annotation-ready).
Validation ensures every item has a question. Editing an item bumps the dataset version (reproducibility).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.evaluation.errors import InvalidDataset
from app.evaluation.interfaces import EvalItemInput
from app.evaluation.models import EvalDataset, EvalItem
from app.evaluation.repository import EvaluationRepository

_DIFFICULTY = ("easy", "medium", "hard")


def validate_item(raw: Dict[str, Any]) -> None:
    q = (raw.get("question") or "").strip()
    if not q:
        raise InvalidDataset("Every item needs a non-empty 'question'.")
    if raw.get("difficulty") and raw["difficulty"] not in _DIFFICULTY:
        raise InvalidDataset(f"difficulty must be one of {_DIFFICULTY}.")


class DatasetManager:
    def __init__(self, db: Session):
        self.db = db
        self.repo = EvaluationRepository(db)

    def create(self, owner_id: str, workspace_id: str, *, name: str, description: Optional[str] = None,
               tags: Optional[List[str]] = None, items: Optional[List[Dict[str, Any]]] = None) -> EvalDataset:
        items = items or []
        for raw in items:
            validate_item(raw)
        ds = EvalDataset(id=f"ds_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
                         name=name, version=1, description=description, tags=tags or None,
                         item_count=len(items))
        self.repo.save_dataset(ds)
        for raw in items:
            self._add_item(ds, owner_id, raw)
        ds.difficulty_distribution = self._difficulty_dist(ds.id)
        self.repo.save_dataset(ds)
        return ds

    def add_items(self, dataset_id: str, owner_id: str, items: List[Dict[str, Any]]) -> EvalDataset:
        ds = self.repo.get_dataset(dataset_id, owner_id)
        if ds is None:
            from app.evaluation.errors import DatasetNotFound
            raise DatasetNotFound(dataset_id)
        for raw in items:
            validate_item(raw)
            self._add_item(ds, owner_id, raw)
        ds.item_count = self.repo.item_count(dataset_id)
        ds.version += 1                          # editing bumps the version (reproducibility)
        ds.difficulty_distribution = self._difficulty_dist(ds.id)
        self.repo.save_dataset(ds)
        return ds

    def _add_item(self, ds: EvalDataset, owner_id: str, raw: Dict[str, Any]) -> EvalItem:
        item = EvalItem(
            id=f"item_{uuid.uuid4().hex[:16]}", dataset_id=ds.id, workspace_id=ds.workspace_id,
            owner_id=owner_id, question=raw["question"], expected_answer=raw.get("expected_answer"),
            ground_truth=raw.get("ground_truth"), relevant_document_ids=raw.get("relevant_document_ids"),
            relevant_chunk_ids=raw.get("relevant_chunk_ids"), relevant_entities=raw.get("relevant_entities"),
            expected_citations=raw.get("expected_citations"),
            expected_relationships=raw.get("expected_relationships"),
            difficulty=raw.get("difficulty", "medium"), tags=raw.get("tags"), meta=raw.get("metadata"))
        return self.repo.save_item(item)

    def _difficulty_dist(self, dataset_id: str) -> Dict[str, int]:
        dist = {d: 0 for d in _DIFFICULTY}
        for it in self.repo.items(dataset_id):
            dist[it.difficulty] = dist.get(it.difficulty, 0) + 1
        return dist

    # ------------------------------------------------------------------ export / load-for-run
    def export(self, dataset_id: str, owner_id: str) -> Dict[str, Any]:
        ds = self.repo.get_dataset(dataset_id, owner_id)
        if ds is None:
            from app.evaluation.errors import DatasetNotFound
            raise DatasetNotFound(dataset_id)
        return {"name": ds.name, "version": ds.version, "description": ds.description, "tags": ds.tags or [],
                "items": [{"question": it.question, "expected_answer": it.expected_answer,
                           "ground_truth": it.ground_truth, "relevant_document_ids": it.relevant_document_ids or [],
                           "relevant_chunk_ids": it.relevant_chunk_ids or [],
                           "relevant_entities": it.relevant_entities or [],
                           "expected_citations": it.expected_citations or [], "difficulty": it.difficulty,
                           "tags": it.tags or []} for it in self.repo.items(dataset_id)]}

    def load_inputs(self, dataset_id: str) -> List[EvalItemInput]:
        return [EvalItemInput(
            id=it.id, question=it.question, expected_answer=it.expected_answer, ground_truth=it.ground_truth,
            relevant_document_ids=it.relevant_document_ids or [], relevant_chunk_ids=it.relevant_chunk_ids or [],
            relevant_entities=it.relevant_entities or [], expected_citations=it.expected_citations or [],
            difficulty=it.difficulty) for it in self.repo.items(dataset_id)]
