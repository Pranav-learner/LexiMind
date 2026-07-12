"""Evaluation domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class EvaluationError(Exception):
    status_code = 400
    code = "evaluation_error"


class DatasetNotFound(EvaluationError):
    status_code = 404
    code = "dataset_not_found"

    def __init__(self, dataset_id: str):
        super().__init__(f"Dataset '{dataset_id}' was not found.")


class RunNotFound(EvaluationError):
    status_code = 404
    code = "run_not_found"

    def __init__(self, run_id: str):
        super().__init__(f"Evaluation run '{run_id}' was not found.")


class PipelineNotFound(EvaluationError):
    status_code = 404
    code = "pipeline_not_found"

    def __init__(self, name: str):
        super().__init__(f"Evaluation pipeline '{name}' is not registered.")


class InvalidDataset(EvaluationError):
    status_code = 422
    code = "invalid_dataset"
