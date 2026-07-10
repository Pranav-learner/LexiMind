"""Chat business logic — conversation lifecycle + the message pipeline.

The message pipeline is a SINGLE generator (`run_message`) that both the streaming (SSE) and the
non-streaming endpoints consume, so there is one code path. It never implements retrieval/context
logic — it delegates to an injected `ChatEngine` (which reuses the existing AI pipeline).

Events yielded by `run_message` (ORM objects; the API serializes them):
    {"type": "user",  "message": Message}                       # persisted user turn
    {"type": "token", "text": str}                              # 0+ progressive tokens
    {"type": "done",  "message": Message, "citations": [MessageCitation]}   # persisted assistant
    {"type": "error", "message": Message, "error": str}         # persisted assistant error turn
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.chat import validation
from app.chat.errors import ConversationNotFound, ConversationStateError
from app.chat.memory import select_history
from app.chat.models import Conversation, Message, MessageCitation
from app.chat.repository import ConversationRepository, MessageRepository
from app.chat.schemas import ArchivedFilter, PinnedFilter, SortField, SortOrder
from app.core.config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChatService:
    def __init__(
        self,
        conv_repo: ConversationRepository,
        msg_repo: MessageRepository,
        workspace_service=None,
    ):
        self.conv = conv_repo
        self.msg = msg_repo
        self.workspace_service = workspace_service

    # ------------------------------------------------------------------ helpers
    def _get_or_404(self, conversation_id: str, owner_id: str) -> Conversation:
        c = self.conv.get(conversation_id, owner_id)
        if c is None:
            raise ConversationNotFound(conversation_id)
        return c

    def _bump_ws(self, workspace_id: str, owner_id: str, delta: int) -> None:
        if self.workspace_service is None:
            return
        try:
            self.workspace_service.adjust_counter(workspace_id, owner_id, "chat_count", delta)
        except Exception:
            pass

    # ------------------------------------------------------------------ conversation commands
    def create(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        document_scope: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        model_name: Optional[str] = None,
    ) -> Conversation:
        conv = Conversation(
            owner_id=owner_id,
            workspace_id=workspace_id,
            title=validation.validate_title(title),
            description=validation.validate_description(description),
            document_scope=document_scope or None,
            temperature=temperature if temperature is not None else 0.7,
            model_name=model_name or settings.llm_model,
        )
        conv = self.conv.create(conv)
        self._bump_ws(workspace_id, owner_id, +1)
        return conv

    def update(
        self,
        conversation_id: str,
        owner_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        document_scope: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        model_name: Optional[str] = None,
    ) -> Conversation:
        c = self._get_or_404(conversation_id, owner_id)
        if title is not None:
            c.title = validation.validate_title(title)
        if description is not None:
            c.description = validation.validate_description(description)
        if document_scope is not None:
            c.document_scope = document_scope or None
        if temperature is not None:
            c.temperature = temperature
        if model_name is not None:
            c.model_name = model_name
        return self.conv.save(c)

    def set_pinned(self, conversation_id: str, owner_id: str, pinned: bool) -> Conversation:
        c = self._get_or_404(conversation_id, owner_id)
        c.is_pinned = pinned
        return self.conv.save(c)

    def archive(self, conversation_id: str, owner_id: str) -> Conversation:
        c = self._get_or_404(conversation_id, owner_id)
        if c.is_archived:
            raise ConversationStateError("Conversation is already archived.")
        c.is_archived = True
        return self.conv.save(c)

    def restore(self, conversation_id: str, owner_id: str) -> Conversation:
        c = self._get_or_404(conversation_id, owner_id)
        if not c.is_archived:
            raise ConversationStateError("Conversation is not archived.")
        c.is_archived = False
        return self.conv.save(c)

    def delete(self, conversation_id: str, owner_id: str, *, permanent: bool = False) -> None:
        c = self._get_or_404(conversation_id, owner_id)
        if permanent:
            self.msg.delete_for_conversation(c.id)
            self.conv.hard_delete(c)
        else:
            self.conv.soft_delete(c)
        self._bump_ws(c.workspace_id, c.owner_id, -1)

    def duplicate(self, conversation_id: str, owner_id: str) -> Conversation:
        src = self._get_or_404(conversation_id, owner_id)
        copy = Conversation(
            owner_id=owner_id,
            workspace_id=src.workspace_id,
            title=validation.validate_title(f"{src.title} (copy)"),
            description=src.description,
            document_scope=src.document_scope,
            temperature=src.temperature,
            model_name=src.model_name,
            system_prompt_version=src.system_prompt_version,
            branched_from_message_id=None,
        )
        copy = self.conv.create(copy)
        # Copy the message history (+citations) in order.
        src_msgs, _ = self.msg.list(src.id, page=1, page_size=10000)
        cit_map = self.msg.citations_for([m.id for m in src_msgs])
        count = 0
        last_at = None
        for m in src_msgs:
            nm = self.msg.add(Message(
                conversation_id=copy.id, role=m.role, content=m.content,
                token_usage=m.token_usage, latency_ms=m.latency_ms, retrieval_ms=m.retrieval_ms,
                context_size=m.context_size, citation_count=m.citation_count, meta=m.meta,
            ))
            self.msg.add_citations([
                MessageCitation(
                    message_id=nm.id, document_id=c.document_id, chunk_id=c.chunk_id,
                    page_number=c.page_number, workspace_id=c.workspace_id,
                    citation_text=c.citation_text, confidence=c.confidence,
                )
                for c in cit_map.get(m.id, [])
            ])
            count += 1
            last_at = nm.created_at
        copy.message_count = count
        copy.last_message_at = last_at
        self.conv.save(copy)
        self._bump_ws(copy.workspace_id, owner_id, +1)
        return copy

    # ------------------------------------------------------------------ conversation queries
    def get(self, conversation_id: str, owner_id: str) -> Conversation:
        return self._get_or_404(conversation_id, owner_id)

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        archived: ArchivedFilter = ArchivedFilter.active,
        pinned: PinnedFilter = PinnedFilter.any,
        sort_by: SortField = SortField.last_message_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Conversation], int]:
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        return self.conv.list(
            owner_id, workspace_id, page=page, page_size=page_size, search=search,
            archived=archived, pinned=pinned, sort_by=sort_by, order=order,
        )

    def search(self, owner_id: str, workspace_id: str, query: str, *, limit: int = 20) -> List[Conversation]:
        if not query or not query.strip():
            return []
        return self.conv.search(owner_id, workspace_id, query, limit=min(max(1, limit), 100))

    def list_messages(
        self, conversation_id: str, owner_id: str, *, page: int = 1, page_size: int = 50
    ) -> Tuple[List[Message], Dict[str, List[MessageCitation]], int]:
        self._get_or_404(conversation_id, owner_id)  # ownership check
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        items, total = self.msg.list(conversation_id, page=page, page_size=page_size)
        cits = self.msg.citations_for([m.id for m in items])
        return items, cits, total

    # ------------------------------------------------------------------ the message pipeline
    def run_message(
        self,
        conversation_id: str,
        owner_id: str,
        content: str,
        engine,
        *,
        top_k: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        conv = self._get_or_404(conversation_id, owner_id)
        content = validation.validate_message_content(content)

        # Build memory from PRIOR turns (before persisting the new user message).
        prior = self.msg.recent(conv.id, limit=settings.chat_history_max_messages * 2)
        history = select_history(
            prior,
            token_budget=settings.chat_history_token_budget,
            max_messages=settings.chat_history_max_messages,
        )

        is_first = conv.message_count == 0
        user_msg = self.msg.add(Message(conversation_id=conv.id, role="user", content=content))
        conv.message_count += 1
        conv.last_message_at = user_msg.created_at
        if is_first and conv.title == validation.DEFAULT_TITLE:
            conv.title = validation.title_from_message(content)
        self.conv.save(conv)
        yield {"type": "user", "message": user_msg}

        # Delegate the actual answer to the injected engine (reuses the AI pipeline).
        answer_parts: List[str] = []
        final: Optional[Dict[str, Any]] = None
        try:
            for ev in engine.generate(
                content, conv.workspace_id, history,
                db=self.conv.db, top_k=top_k, document_scope=conv.document_scope,
            ):
                if ev.get("type") == "token":
                    answer_parts.append(ev.get("text", ""))
                    yield {"type": "token", "text": ev.get("text", "")}
                elif ev.get("type") == "final":
                    final = ev
        except Exception as e:  # persist a failed assistant turn so history stays consistent
            err_msg = self.msg.add(Message(
                conversation_id=conv.id, role="assistant",
                content="".join(answer_parts), meta={"status": "error", "error": str(e)},
            ))
            conv.message_count += 1
            conv.last_message_at = err_msg.created_at
            self.conv.save(conv)
            yield {"type": "error", "message": err_msg, "error": str(e)}
            return

        answer = (final or {}).get("answer") or "".join(answer_parts).strip()
        citations = (final or {}).get("citations", [])
        assistant = self.msg.add(Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            token_usage=int((final or {}).get("token_usage", 0)),
            latency_ms=int((final or {}).get("latency_ms", 0)),
            retrieval_ms=int((final or {}).get("retrieval_ms", 0)),
            context_size=int((final or {}).get("context_size", 0)),
            citation_count=len(citations),
            meta={"status": "ok", "model": conv.model_name},
        ))
        cit_rows = self.msg.add_citations([
            MessageCitation(
                message_id=assistant.id,
                document_id=c.get("document_id"),
                chunk_id=c.get("chunk_id"),
                page_number=c.get("page_number"),
                workspace_id=conv.workspace_id,
                citation_text=(c.get("text") or c.get("source") or "")[:2000],
                confidence=c.get("confidence"),
            )
            for c in citations
        ])
        conv.message_count += 1
        conv.last_message_at = assistant.created_at
        self.conv.save(conv)
        yield {"type": "done", "message": assistant, "citations": cit_rows}
