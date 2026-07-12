"""Instrumented pipeline (Steps 3 & 14) — distributed tracing WRAPPING the real production pipeline.

`traced_query` runs an actual answer request — retrieval → context (PromptPackage) → AnswerService →
Verification — with each stage inside a span, producing one complete parent-child trace with a latency
waterfall + per-span tokens. It composes the SAME production services the agents/eval use (no duplicated
execution path); the tracer just observes them. This is the reference instrumentation the other
subsystems adopt via the `Tracer`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.observability.tracer import Tracer


def traced_query(db: Session, workspace_id: str, owner_id: str, *, question: str,
                 services: Dict[str, Any], hops: int = 2) -> Dict[str, Any]:
    tracer = Tracer(db, workspace_id, owner_id)
    answer = ""
    trace_id = ""
    with tracer.trace("query", question=question[:200]) as tr:
        trace_id = tr.record.id

        # 1) retrieval span (real unified retrieval)
        results = []
        with tr.span("retrieval", component="retrieval") as s:
            try:
                from app.mmretrieval.repository import RetrievalRepository
                from app.mmretrieval.schemas import SearchRequest
                from app.mmretrieval.service import MultimodalRetrievalService
                res = MultimodalRetrievalService(RetrievalRepository(db)).search(
                    owner_id, workspace_id, SearchRequest(query=question, top_k=8, explain=False))
                results = res.get("results", [])
                s.set_attribute("results", len(results))
            except Exception as e:
                s.set_error(str(e))

        # 2) graph retrieval span (real semantic memory) — optional
        with tr.span("graph_retrieval", component="graph") as s:
            try:
                from app.memory.service import SemanticMemoryService
                mem = SemanticMemoryService(db).retrieve(workspace_id, owner_id, query=question, hops=hops,
                                                         limit=8, persist=False)
                s.set_attribute("graph_hits", len(mem.get("hits", [])))
            except Exception as e:
                s.set_error(str(e))

        # 3) context / prompt-package span
        with tr.span("context", component="context_engineering") as s:
            from app.agents.prompt_package import PromptPackage, PromptSection
            evidence = [{"index": i, "text": (r.get("content") or ""), "document_id": r.get("document_id"),
                         "score": float(r.get("confidence") or 0.5)} for i, r in enumerate(results, start=1)]
            pkg = PromptPackage(query=question)
            if evidence:
                pkg.sections.append(PromptSection(title="Evidence",
                                    content="\n".join(f"[{e['index']}] {e['text']}" for e in evidence)))
            prompt = pkg.render()
            s.set_attribute("context_chars", len(prompt)); s.add_tokens(len(prompt) // 4)

        # 4) answer span — SINGLE AnswerService pathway
        with tr.span("answer", component="answer_service") as s:
            answer_fn = services.get("answer_fn")
            answer = (answer_fn(prompt) if answer_fn else "").strip()
            s.add_tokens(len(answer) // 4); s.set_attribute("answer_chars", len(answer))

        # 5) verification span (reuse Verification Engine)
        with tr.span("verification", component="verification") as s:
            try:
                from app.reasoning.repository import VerificationRepository
                from app.reasoning.service import VerificationService
                v = VerificationService(VerificationRepository(db)).verify(
                    workspace_id, owner_id, answer_text=answer, evidence=evidence, mode="fast",
                    signals={"success": bool(answer)}, agent="observability", task_type="traced_query",
                    persist=False)
                s.set_attribute("verification_status", v.get("status"))
            except Exception as e:
                s.set_error(str(e))

    return {"trace_id": trace_id, "answer": answer}
