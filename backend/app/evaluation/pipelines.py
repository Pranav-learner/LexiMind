"""Benchmarkable pipelines (Steps 4 & 14) — each executes the REAL production services.

A `Pipeline` runs an actual LexiMind subsystem on a golden item and returns a uniform `PipelineOutput`
the metric engine scores. No shadow/duplicated execution path: retrieval pipelines call the Phase-4/5/7
retrieval services; the answer pipeline reuses the single `answer_fn` (AnswerService) + the Verification
Engine. New pipelines register here with no runner change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.evaluation.interfaces import EvalItemInput, PipelineOutput, RetrievedRef


@dataclass
class EvalContext:
    db: Session
    workspace_id: str
    owner_id: str
    services: Dict[str, Any]


# --------------------------------------------------------------------- retrieval pipelines
class WorkspaceRetrievalPipeline:
    """Phase-1/4 unified retrieval (dense + sparse + multimodal fusion)."""
    name = "workspace_retrieval"
    version = "v1"

    def run(self, ctx: EvalContext, item: EvalItemInput) -> PipelineOutput:
        t = time.perf_counter()
        try:
            from app.mmretrieval.repository import RetrievalRepository
            from app.mmretrieval.schemas import SearchRequest
            from app.mmretrieval.service import MultimodalRetrievalService
            res = MultimodalRetrievalService(RetrievalRepository(ctx.db)).search(
                ctx.owner_id, ctx.workspace_id, SearchRequest(query=item.question, top_k=10, explain=False))
            refs = [RetrievedRef(chunk_id=r.get("chunk_id"), document_id=r.get("document_id"),
                                 source=r.get("title"), score=float(r.get("confidence") or 0.0))
                    for r in res.get("results", [])]
            return PipelineOutput(retrieved=refs, latency_ms=(time.perf_counter() - t) * 1000)
        except Exception as e:
            return PipelineOutput(latency_ms=(time.perf_counter() - t) * 1000, error=str(e)[:300])


class GraphRetrievalPipeline:
    """Phase-7 semantic memory / graph retrieval."""
    name = "graph_retrieval"
    version = "v1"

    def run(self, ctx: EvalContext, item: EvalItemInput) -> PipelineOutput:
        t = time.perf_counter()
        try:
            from app.memory.service import SemanticMemoryService
            res = SemanticMemoryService(ctx.db).retrieve(ctx.workspace_id, ctx.owner_id, query=item.question,
                                                         hops=2, limit=10, persist=False)
            refs = [RetrievedRef(entity=h.get("canonical_name"), document_id=None,
                                 source=h.get("kind"), score=float(h.get("score") or 0.0))
                    for h in res.get("hits", [])]
            return PipelineOutput(retrieved=refs, citations=res.get("citations", []),
                                  context_size=len(res.get("context_text", "")),
                                  latency_ms=(time.perf_counter() - t) * 1000)
        except Exception as e:
            return PipelineOutput(latency_ms=(time.perf_counter() - t) * 1000, error=str(e)[:300])


class TemporalRetrievalPipeline:
    """Phase-5 temporal retrieval (recordings by time/speaker/topic)."""
    name = "temporal_retrieval"
    version = "v1"

    def run(self, ctx: EvalContext, item: EvalItemInput) -> PipelineOutput:
        t = time.perf_counter()
        try:
            from app.tretrieval.repository import TemporalRepository
            from app.tretrieval.schemas import TemporalSearchRequest
            from app.tretrieval.service import TemporalRetrievalService
            res = TemporalRetrievalService(TemporalRepository(ctx.db)).search(
                ctx.owner_id, ctx.workspace_id,
                TemporalSearchRequest(query=item.question, top_k=10, build_context=False, explain=False))
            refs = [RetrievedRef(chunk_id=r.get("key"), document_id=r.get("document_id"),
                                 source=r.get("source_type"), score=float(r.get("confidence") or 0.0))
                    for r in res.get("results", [])]
            return PipelineOutput(retrieved=refs, latency_ms=(time.perf_counter() - t) * 1000)
        except Exception as e:
            return PipelineOutput(latency_ms=(time.perf_counter() - t) * 1000, error=str(e)[:300])


# --------------------------------------------------------------------- answer pipeline (full)
class AnswerPipeline:
    """The full answer pipeline: retrieval → PromptPackage → single AnswerService → Verification."""
    name = "answer"
    version = "v1"

    def run(self, ctx: EvalContext, item: EvalItemInput) -> PipelineOutput:
        t = time.perf_counter()
        try:
            from app.agents.prompt_package import PromptPackage, PromptSection
            from app.mmretrieval.repository import RetrievalRepository
            from app.mmretrieval.schemas import SearchRequest
            from app.mmretrieval.service import MultimodalRetrievalService
            res = MultimodalRetrievalService(RetrievalRepository(ctx.db)).search(
                ctx.owner_id, ctx.workspace_id, SearchRequest(query=item.question, top_k=8, explain=False))
            results = res.get("results", [])
            refs = [RetrievedRef(chunk_id=r.get("chunk_id"), document_id=r.get("document_id"),
                                 source=r.get("title"), score=float(r.get("confidence") or 0.0))
                    for r in results]
            evidence, citations = [], []
            for i, r in enumerate(results, start=1):
                text = (r.get("content") or "").strip()
                evidence.append({"index": i, "text": text, "document_id": r.get("document_id"),
                                 "score": float(r.get("confidence") or 0.5)})
                citations.append({"index": i, "document_id": r.get("document_id"), "text": text[:300]})

            pkg = PromptPackage(query=item.question)
            if evidence:
                pkg.sections.append(PromptSection(title="Evidence",
                                    content="\n".join(f"[{e['index']}] {e['text']}" for e in evidence)))
            pkg.citations = citations
            prompt = pkg.render()
            answer_fn = ctx.services.get("answer_fn")
            answer = (answer_fn(prompt) if answer_fn else "").strip()

            # verification (reuse the Verification Engine — hallucination/confidence signal)
            verification = None
            try:
                from app.reasoning.repository import VerificationRepository
                from app.reasoning.service import VerificationService
                verification = VerificationService(VerificationRepository(ctx.db)).verify(
                    ctx.workspace_id, ctx.owner_id, answer_text=answer, evidence=evidence, mode="fast",
                    signals={"success": bool(answer)}, agent="evaluator", task_type="evaluation",
                    persist=False)
            except Exception:
                pass
            conf = ((verification or {}).get("confidence") or {}).get("overall")
            return PipelineOutput(retrieved=refs, answer=answer, citations=citations, evidence=evidence,
                                  confidence=conf, verification=verification,
                                  token_usage=max(0, (len(prompt) + len(answer)) // 4),
                                  context_size=len(prompt), latency_ms=(time.perf_counter() - t) * 1000)
        except Exception as e:
            return PipelineOutput(latency_ms=(time.perf_counter() - t) * 1000, error=str(e)[:300])


_PIPELINES = {p.name: p for p in [WorkspaceRetrievalPipeline(), GraphRetrievalPipeline(),
                                  TemporalRetrievalPipeline(), AnswerPipeline()]}


def get_pipeline(name: str):
    p = _PIPELINES.get(name)
    if p is None:
        from app.evaluation.errors import PipelineNotFound
        raise PipelineNotFound(name)
    return p


def list_pipelines() -> List[Dict[str, str]]:
    return [{"name": p.name, "version": p.version,
             "kind": "answer" if p.name == "answer" else "retrieval"} for p in _PIPELINES.values()]
