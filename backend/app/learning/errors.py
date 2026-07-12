"""Continuous-learning domain errors (transport-agnostic; each carries a `status_code`)."""

from __future__ import annotations


class LearningError(Exception):
    status_code = 400
    code = "learning_error"


class RecommendationNotFound(LearningError):
    status_code = 404
    code = "recommendation_not_found"

    def __init__(self, rec_id: str):
        super().__init__(f"Recommendation '{rec_id}' was not found.")
