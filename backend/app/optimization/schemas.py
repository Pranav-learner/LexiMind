"""DTOs for the AI Optimization & Cost Intelligence API (Phase 8, Module 3)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

_POLICY_PATTERN = "^(balanced|lowest_cost|highest_quality|fastest|research|offline|developer|enterprise)$"


class OptimizeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    policy: Optional[str] = Field(default=None, pattern=_POLICY_PATTERN)


class SetPolicyRequest(BaseModel):
    policy: str = Field(pattern=_POLICY_PATTERN)
