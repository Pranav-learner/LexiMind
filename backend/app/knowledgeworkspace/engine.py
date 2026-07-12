"""AI Graph Chat engine (Step 7 / 17) — a chat engine that grounds answers in graph knowledge.

Implements the EXISTING chat-engine interface (`generate(content, workspace_id, history, *, db, top_k,
document_scope)`) so AI Graph Chat runs through the UNCHANGED `ChatService.run_message` — same
Conversation/Message/MessageCitation persistence, same history, same event contract as normal chat
(exactly the Phase-5 TemporalChatEngine pattern). It composes Module-2 graph retrieval + Module-3 graph
reasoning into ONE grounded prompt and hands it to the injected `answer_fn` (prod =
`answer_service.complete`, tests = fake) — the SINGLE AnswerService inference pathway. No second LLM path.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional

_SYSTEM = (
    "You are LexiMind's Knowledge Graph assistant. Answer the user's question using ONLY the graph "
    "knowledge and reasoning paths below. Cite claims with the bracketed [n] markers, explain how "
    "entities are connected when relevant, and if the graph does not contain the answer, say so plainly."
)


class GraphChatEngine:
    def __init__(self, answer_fn=None, *, top_k: int = 12):
        self._answer_fn = answer_fn
        self.top_k = top_k
        self.last_result: Dict[str, Any] = {}

    def _answer(self):
        if self._answer_fn is not None:
            return self._answer_fn
        from app.services import answer_service
        return answer_service.complete

    def generate(self, content: str, workspace_id: str, history: Optional[List[Dict[str, Any]]] = None,
                 *, db=None, top_k: Optional[int] = None, document_scope: Optional[List[str]] = None
                 ) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        k = top_k or self.top_k
        owner_id = self._owner(db, workspace_id)

        # 1) graph retrieval (Module 2) + 2) graph reasoning (Module 3) — reused, no new retrieval
        retrieval_ms = 0.0
        graph_ctx = ""
        reason_ctx = ""
        citations: List[Dict[str, Any]] = []
        try:
            from app.memory.service import SemanticMemoryService
            t = time.perf_counter()
            mem = SemanticMemoryService(db).retrieve(workspace_id, owner_id, query=content, hops=2,
                                                     limit=k, persist=False)
            retrieval_ms = (time.perf_counter() - t) * 1000
            graph_ctx = mem.get("context_text", "")
            citations = self._map_citations(mem.get("citations", []))
        except Exception:
            pass
        try:
            from app.graphreason.service import GraphReasoningService
            reason = GraphReasoningService(db).reason(workspace_id, owner_id, query=content, hops=3,
                                                      verify=False, persist=False, persist_inferences=False)
            reason_ctx = reason.get("context_text", "")
        except Exception:
            pass

        if not (graph_ctx or reason_ctx):
            yield {"type": "final", "answer": ("I don't have graph knowledge about that yet — build the "
                   "knowledge graph for this workspace first."), "citations": [],
                   "retrieval_ms": int(retrieval_ms), "context_size": 0, "token_usage": 0,
                   "latency_ms": int((time.perf_counter() - started) * 1000)}
            self.last_result = {"citations": [], "grounded": False}
            return

        # 3) build ONE grounded prompt → single AnswerService pathway
        prompt = self._prompt(content, graph_ctx, reason_ctx, history)
        try:
            answer = (self._answer()(prompt) or "").strip()
        except Exception as e:
            answer = f"(graph answer unavailable: {e})"
        latency_ms = int((time.perf_counter() - started) * 1000)
        self.last_result = {"citations": citations, "grounded": True}
        yield {"type": "final", "answer": answer, "citations": citations,
               "retrieval_ms": int(retrieval_ms), "context_size": len(graph_ctx) + len(reason_ctx),
               "token_usage": len(answer.split()), "latency_ms": latency_ms}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _owner(db, workspace_id: str) -> str:
        from app.workspaces.models import Workspace
        ws = db.get(Workspace, workspace_id)
        return ws.owner_id if ws is not None else ""

    @staticmethod
    def _map_citations(graph_citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for c in graph_citations:
            out.append({"document_id": c.get("document_id"), "chunk_id": c.get("entity_id") or c.get("rel_id"),
                        "page_number": None, "text": (c.get("text") or "")[:400],
                        "source": c.get("name") or c.get("kind") or "graph",
                        "confidence": float(c.get("confidence") or c.get("score") or 0.5)})
        return out

    @staticmethod
    def _prompt(question: str, graph_ctx: str, reason_ctx: str, history) -> str:
        from app.chat.memory import render_history
        transcript = render_history(history or [])
        hist_block = f"\nConversation so far:\n{transcript}\n" if transcript else ""
        knowledge = "\n\n".join(x for x in (graph_ctx, reason_ctx) if x)
        return (f"{_SYSTEM}\n{hist_block}\nGraph knowledge:\n{knowledge}\n\n"
                f"User: {question}\n\nAssistant:\n")
