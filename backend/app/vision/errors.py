"""Vision Intelligence domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class VisionError(Exception):
    status_code = 400
    code = "vision_error"


class JobNotFound(VisionError):
    status_code = 404
    code = "vision_job_not_found"

    def __init__(self, job_id: str):
        super().__init__(f"Vision job '{job_id}' was not found.")


class AnalysisNotFound(VisionError):
    status_code = 404
    code = "analysis_not_found"

    def __init__(self, analysis_id: str):
        super().__init__(f"Vision analysis '{analysis_id}' was not found.")


class DocumentNotFound(VisionError):
    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str):
        super().__init__(f"Document '{document_id}' was not found in this workspace.")


class VisionStateError(VisionError):
    """Illegal state transition (e.g. cancelling a completed job)."""

    status_code = 409
    code = "invalid_state"
