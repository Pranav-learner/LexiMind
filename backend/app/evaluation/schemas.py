"""DTOs for the AI Evaluation & Benchmarking API (Phase 8, Module 1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DatasetItemIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    expected_answer: Optional[str] = None
    ground_truth: Optional[str] = None
    relevant_document_ids: List[str] = []
    relevant_chunk_ids: List[str] = []
    relevant_entities: List[str] = []
    expected_citations: List[Dict[str, Any]] = []
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    tags: List[str] = []


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    tags: List[str] = []
    items: List[DatasetItemIn] = []


class ImportDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    tags: List[str] = []
    items: List[Dict[str, Any]] = []


class RunBenchmarkRequest(BaseModel):
    dataset_id: str
    pipeline: str
    use_judge: bool = False
    label: Optional[str] = Field(default=None, max_length=120)
    thresholds: Optional[Dict[str, float]] = None
    use_cache: bool = True


class RegressionRequest(BaseModel):
    baseline_run_id: Optional[str] = None


class CompareRequest(BaseModel):
    a_run_id: str
    b_run_id: str
