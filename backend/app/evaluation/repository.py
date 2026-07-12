"""Data access for evaluation — datasets, items, and run logs (workspace + owner scoped)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.evaluation.models import EvalDataset, EvalItem, EvaluationRunLog


class EvaluationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ datasets
    def save_dataset(self, ds: EvalDataset) -> EvalDataset:
        self.db.add(ds); self.db.commit(); self.db.refresh(ds); return ds

    def get_dataset(self, dataset_id: str, owner_id: str) -> Optional[EvalDataset]:
        return self.db.scalar(select(EvalDataset).where(
            EvalDataset.id == dataset_id, EvalDataset.owner_id == owner_id))

    def datasets(self, workspace_id: str, owner_id: str, *, limit: int = 50) -> List[EvalDataset]:
        return list(self.db.scalars(select(EvalDataset).where(
            EvalDataset.workspace_id == workspace_id, EvalDataset.owner_id == owner_id)
            .order_by(desc(EvalDataset.created_at)).limit(limit)))

    def save_item(self, item: EvalItem) -> EvalItem:
        self.db.add(item); self.db.commit(); return item

    def items(self, dataset_id: str) -> List[EvalItem]:
        return list(self.db.scalars(select(EvalItem).where(EvalItem.dataset_id == dataset_id)
                                    .order_by(asc(EvalItem.created_at))))

    def item_count(self, dataset_id: str) -> int:
        return int(self.db.scalar(select(func.count()).select_from(EvalItem).where(
            EvalItem.dataset_id == dataset_id)) or 0)

    # ------------------------------------------------------------------ run logs
    def save_run(self, run: EvaluationRunLog) -> EvaluationRunLog:
        self.db.add(run); self.db.commit(); self.db.refresh(run); return run

    def get_run(self, run_id: str, owner_id: str) -> Optional[EvaluationRunLog]:
        return self.db.scalar(select(EvaluationRunLog).where(
            EvaluationRunLog.id == run_id, EvaluationRunLog.owner_id == owner_id))

    def runs(self, workspace_id: str, owner_id: str, *, dataset_id: Optional[str] = None,
             pipeline: Optional[str] = None, limit: int = 50) -> List[EvaluationRunLog]:
        stmt = select(EvaluationRunLog).where(
            EvaluationRunLog.workspace_id == workspace_id, EvaluationRunLog.owner_id == owner_id)
        if dataset_id:
            stmt = stmt.where(EvaluationRunLog.dataset_id == dataset_id)
        if pipeline:
            stmt = stmt.where(EvaluationRunLog.pipeline == pipeline)
        return list(self.db.scalars(stmt.order_by(desc(EvaluationRunLog.created_at)).limit(limit)))

    def latest_run(self, workspace_id: str, owner_id: str, *, dataset_id: str, pipeline: str,
                   exclude_id: Optional[str] = None) -> Optional[EvaluationRunLog]:
        stmt = select(EvaluationRunLog).where(
            EvaluationRunLog.workspace_id == workspace_id, EvaluationRunLog.owner_id == owner_id,
            EvaluationRunLog.dataset_id == dataset_id, EvaluationRunLog.pipeline == pipeline,
            EvaluationRunLog.status == "completed")
        if exclude_id:
            stmt = stmt.where(EvaluationRunLog.id != exclude_id)
        return self.db.scalar(stmt.order_by(desc(EvaluationRunLog.created_at)))
