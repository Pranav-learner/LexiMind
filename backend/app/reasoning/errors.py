"""Verification domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class VerificationError(Exception):
    status_code = 400
    code = "verification_error"


class VerificationNotFound(VerificationError):
    status_code = 404
    code = "verification_not_found"

    def __init__(self, ref: str):
        super().__init__(f"No verification was found for '{ref}'.")
