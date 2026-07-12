"""The Temporal Chat Engine — media AI chat that plugs into the EXISTING chat pipeline.

Step 3 mandate: "Do not build a second chat system. Reuse the existing chat architecture." This
engine implements the SAME interface the Phase-3 `ChatService.run_message` already delegates to
(`generate(content, workspace_id, history, *, db, top_k, document_scope) -> events`), so a media
conversation is a NORMAL `Conversation` whose turns run through the unchanged chat pipeline
(persistence, history, citations, streaming). The only difference is WHERE the answer comes from:

    temporal retrieval (app.tretrieval)  →  timestamp-preserving prompt  →  answer_service.complete

i.e. this finally wires the single LLM pathway that Module 3 left as an inspectable prompt preview.
`answer_fn` is injected (production = `app.services.answer_service.complete`; tests pass a fake), so
no LLM/ollama runs in the test suite. Owner is derived from the workspace row, so the chat interface
is reused verbatim (no signature change to ChatService / FakeChatEngine).

The engine maps temporal citations (timespan / speaker / scene / frame) into the chat citation dict
shape AND stashes the rich citations on `self.last_result` for the orchestrator to surface.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional


class TemporalChatEngine:
    def __init__(self, answer_fn=None, *, top_k: int = 12):
        self._answer_fn = answer_fn
        self.top_k = top_k
        self.last_result: Dict[str, Any] = {}

    def _answer(self, prompt: str) -> str:
        if self._answer_fn is not None:
            return self._answer_fn(prompt)
        from app.services import answer_service
        return answer_service.complete(prompt)

    def generate(self, content: str, workspace_id: str, history: Optional[List[Dict[str, Any]]] = None,
                 *, db=None, top_k: Optional[int] = None, document_scope: Optional[List[str]] = None
                 ) -> Iterator[Dict[str, Any]]:
        started = time.perf_counter()
        # Owner is derivable from the workspace (one owner per workspace) — keeps the chat interface intact.
        owner_id = self._owner(db, workspace_id)
        document_id = document_scope[0] if document_scope else None

        from app.tretrieval.repository import TemporalRepository
        from app.tretrieval.schemas import TemporalSearchRequest
        from app.tretrieval.service import TemporalRetrievalService

        req = TemporalSearchRequest(query=content, document_id=document_id,
                                    top_k=top_k or self.top_k, build_context=True, explain=False)
        svc = TemporalRetrievalService(TemporalRepository(db))
        result = svc.search(owner_id, workspace_id, req)

        prompt = result.get("prompt")
        retrieval_ms = int(result.get("total_ms", 0))
        context_blocks = result.get("context_blocks") or []
        context_size = sum(int(b.get("tokens", 0)) for b in context_blocks)

        if not prompt:
            # No temporal evidence — answer honestly without calling the LLM on an empty prompt.
            answer = ("I couldn't find any relevant moment in the processed media for that question. "
                      "Try uploading/processing a recording first, or rephrase your question.")
            self.last_result = {"citations": [], "temporal": result, "grounded": False}
            yield {"type": "final", "answer": answer, "citations": [], "retrieval_ms": retrieval_ms,
                   "context_size": 0, "token_usage": 0, "latency_ms": int((time.perf_counter() - started) * 1000)}
            return

        answer = self._answer(prompt).strip() or "(no answer generated)"

        rich = result.get("citations", [])
        chat_citations = [self._to_chat_citation(c) for c in rich]
        self.last_result = {"citations": rich, "temporal": result, "grounded": True,
                            "prompt": prompt, "primary": result.get("primary")}

        yield {"type": "final", "answer": answer, "citations": chat_citations,
               "retrieval_ms": retrieval_ms, "context_size": context_size,
               "token_usage": len(answer.split()),
               "latency_ms": int((time.perf_counter() - started) * 1000)}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _owner(db, workspace_id: str) -> str:
        from app.workspaces.models import Workspace
        ws = db.get(Workspace, workspace_id) if db is not None else None
        return ws.owner_id if ws is not None else ""

    @staticmethod
    def _to_chat_citation(c: Dict[str, Any]) -> Dict[str, Any]:
        """Map a temporal citation into the chat citation dict shape (persisted by ChatService), while
        keeping timestamp/speaker info in `chunk_id` + `text` so the frontend can seek the player."""
        start = int(c.get("start_ms", 0))
        end = int(c.get("end_ms", 0))
        speaker = c.get("speaker_label", "")
        prefix = f"[{c.get('timespan', '')}{' · ' + speaker if speaker else ''}] "
        return {
            "document_id": c.get("document_id"),
            "chunk_id": f"{start}:{end}",              # frontend parses start_ms to seek
            "page_number": None,
            "text": (prefix + (c.get("text", "") or ""))[:2000],
            "confidence": None,
            # extra keys (ignored by chat persistence, surfaced by the orchestrator response):
            "start_ms": start, "end_ms": end, "timespan": c.get("timespan", ""),
            "speaker_label": speaker, "modality": c.get("modality"), "index": c.get("index"),
            "scene_id": c.get("scene_id"), "frame_id": c.get("frame_id"),
        }
