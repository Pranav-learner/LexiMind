"""Verification service — coordinate the Reasoning Engine + persist telemetry + expose history.

Thin coordination over the `ReasoningEngine` (compute) and the repository (`VerificationLog`). Two entry
points that matter:
- `verify(...)`            — ad-hoc: verify an answer against supplied evidence (developer/manual API).
- `verify_task_result(...)`— the AGENT-INTEGRATION seam: verify a Module-2 `AgentTaskResult` in place,
                             using the answer it already produced + the evidence it already retrieved
                             (NO re-retrieval, NO second LLM orchestration; `thorough` adds one optional
                             critique through the SAME `answer_fn`).

It contains no reasoning logic — that lives in the engine's injectable stages.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.reasoning.engine import ReasoningEngine
from app.reasoning.errors import VerificationNotFound
from app.reasoning.interfaces import VerificationReport
from app.reasoning.models import VerificationLog
from app.reasoning.repository import VerificationRepository


def answer_text_from_output(output: Optional[Dict[str, Any]]) -> str:
    """Reconstruct the checkable prose from a StructuredOutput dict (markdown blocks = the narrative)."""
    if not output:
        return ""
    blocks = output.get("blocks") or []
    prose = [str(b.get("content") or "") for b in blocks if b.get("type") == "markdown"]
    return "\n\n".join(p for p in prose if p.strip()) or (output.get("summary") or "")


def evidence_from_output(output: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Use the deliverable's persisted citations as the evidence pool for re-verification."""
    return list((output or {}).get("citations") or [])


class VerificationService:
    def __init__(self, repo: VerificationRepository, *, engine: Optional[ReasoningEngine] = None):
        self.repo = repo
        self.db = repo.db
        self.engine = engine or ReasoningEngine()

    # ------------------------------------------------------------------ core verify + persist
    def verify(self, workspace_id: str, owner_id: str, *, answer_text: str, evidence: List[Any],
               mode: str = "fast", signals: Optional[Dict[str, Any]] = None, answer_fn=None,
               execution_id: Optional[str] = None, agent: str = "", task_type: str = "",
               persist: bool = True) -> Dict[str, Any]:
        report = self.engine.verify(answer_text=answer_text, evidence=evidence, mode=mode,
                                    signals=signals or {}, answer_fn=answer_fn)
        if persist:
            self._persist(workspace_id, owner_id, report, execution_id=execution_id, agent=agent,
                          task_type=task_type)
        return report.to_dict()

    def verify_task_result(self, result, ctx, *, mode: str = "fast", persist: bool = True) -> Dict[str, Any]:
        """Agent-integration seam: verify a Module-2 AgentTaskResult using its own answer + evidence."""
        output = result.output.to_dict() if result.output is not None else {}
        answer_text = answer_text_from_output(output)
        signals = {"success": result.success, "execution_success": 1.0 if result.success else 0.3}
        answer_fn = ctx.answer_fn() if (mode == "thorough" and getattr(ctx, "services", None)) else None
        return self.verify(ctx.workspace_id, ctx.owner_id, answer_text=answer_text,
                           evidence=result.evidence, mode=mode, signals=signals, answer_fn=answer_fn,
                           execution_id=result.task_id, agent=result.agent, task_type=result.task_type,
                           persist=persist)

    def verify_stored_task(self, workspace_id: str, owner_id: str, task_id: str, *, mode: str = "fast",
                           answer_fn=None) -> Dict[str, Any]:
        """Re-verify a persisted agent task from its stored deliverable (developer API)."""
        from app.agents.task_repository import AgentTaskRepository
        log = AgentTaskRepository(self.db).get(task_id, owner_id)
        if log is None:
            raise VerificationNotFound(task_id)
        answer_text = answer_text_from_output(log.output)
        evidence = evidence_from_output(log.output)
        signals = {"success": log.success, "execution_success": 1.0 if log.success else 0.3}
        return self.verify(workspace_id, owner_id, answer_text=answer_text, evidence=evidence, mode=mode,
                           signals=signals, answer_fn=answer_fn, execution_id=task_id, agent=log.agent,
                           task_type=log.task_type)

    def _persist(self, workspace_id: str, owner_id: str, report: VerificationReport, *,
                 execution_id: Optional[str], agent: str, task_type: str) -> VerificationLog:
        c = report.counts
        from app.reasoning.interfaces import CONFLICTING, SUPPORTED, UNSUPPORTED, WEAK
        citation_failures = sum(1 for i in report.citation_issues
                                if i.issue_type in ("broken", "missing"))
        log = VerificationLog(
            id=f"ver_{uuid.uuid4().hex[:16]}", workspace_id=workspace_id, owner_id=owner_id,
            execution_id=execution_id, agent=agent, task_type=task_type, mode=report.mode,
            status=report.status, overall_confidence=report.confidence.overall,
            confidence_band=report.confidence.band, claims_total=len(report.claim_verdicts),
            supported=c[SUPPORTED], weak=c[WEAK], unsupported=c[UNSUPPORTED], conflicting=c[CONFLICTING],
            contradictions_found=len(report.contradictions), citation_failures=citation_failures,
            evidence_used=len(report.evidence), warnings_count=len(report.warnings),
            verification_ms=report.timings.get("total_ms", 0.0),
            review_ms=report.timings.get("review_ms", 0.0), report=report.to_dict())
        return self.repo.save(log)

    # ------------------------------------------------------------------ reads
    def get(self, verification_id: str, owner_id: str) -> VerificationLog:
        log = self.repo.get(verification_id, owner_id)
        if log is None:
            raise VerificationNotFound(verification_id)
        return log

    def for_execution(self, execution_id: str, owner_id: str) -> VerificationLog:
        log = self.repo.get_for_execution(execution_id, owner_id)
        if log is None:
            raise VerificationNotFound(execution_id)
        return log

    def history(self, workspace_id: str, owner_id: str, *, limit: int = 30) -> List[VerificationLog]:
        return self.repo.list(workspace_id, owner_id, limit=limit)

    def stats(self, workspace_id: str) -> Dict[str, Any]:
        return self.repo.stats(workspace_id)
