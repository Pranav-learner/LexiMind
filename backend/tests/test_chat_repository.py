"""Unit tests for chat repositories against in-memory SQLite."""

from __future__ import annotations

from app.chat.models import Conversation, Message, MessageCitation
from app.chat.repository import ConversationRepository, MessageRepository
from app.chat.schemas import ArchivedFilter, PinnedFilter, SortField, SortOrder

OWNER = "user_1"
WS = "ws_1"


def _conv(repo, *, title="Chat", archived=False, pinned=False, owner=OWNER, ws=WS, desc=""):
    return repo.create(Conversation(
        owner_id=owner, workspace_id=ws, title=title, description=desc,
        is_archived=archived, is_pinned=pinned,
    ))


def test_get_owner_scoped(db_session):
    repo = ConversationRepository(db_session)
    c = _conv(repo)
    assert repo.get(c.id, OWNER) is not None
    assert repo.get(c.id, "other") is None


def test_soft_delete_hides(db_session):
    repo = ConversationRepository(db_session)
    c = _conv(repo)
    repo.soft_delete(c)
    assert repo.get(c.id, OWNER) is None
    assert repo.list(OWNER, WS)[1] == 0


def test_list_filters_and_pinned_first(db_session):
    repo = ConversationRepository(db_session)
    _conv(repo, title="plain")
    _conv(repo, title="pinned one", pinned=True)
    _conv(repo, title="archived one", archived=True)

    assert repo.list(OWNER, WS, archived=ArchivedFilter.active)[1] == 2
    assert repo.list(OWNER, WS, archived=ArchivedFilter.archived)[1] == 1
    assert repo.list(OWNER, WS, archived=ArchivedFilter.all)[1] == 3
    assert repo.list(OWNER, WS, pinned=PinnedFilter.pinned)[1] == 1

    items, _ = repo.list(OWNER, WS, archived=ArchivedFilter.active, sort_by=SortField.title, order=SortOrder.asc)
    assert items[0].is_pinned is True  # pinned floats to the top regardless of sort


def test_list_search_title_description(db_session):
    repo = ConversationRepository(db_session)
    _conv(repo, title="Operating Systems", desc="paging")
    _conv(repo, title="Machine Learning", desc="gradients")
    assert repo.list(OWNER, WS, search="operating")[1] == 1
    assert repo.list(OWNER, WS, search="gradients")[1] == 1


def test_broad_search_includes_messages_and_citations(db_session):
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)
    c1 = _conv(conv_repo, title="Alpha")
    c2 = _conv(conv_repo, title="Beta")
    m = msg_repo.add(Message(conversation_id=c1.id, role="user", content="tell me about mitochondria"))
    a = msg_repo.add(Message(conversation_id=c2.id, role="assistant", content="see source"))
    msg_repo.add_citations([MessageCitation(message_id=a.id, workspace_id=WS, citation_text="ribosome function")])

    assert {c.id for c in conv_repo.search(OWNER, WS, "mitochondria")} == {c1.id}
    assert {c.id for c in conv_repo.search(OWNER, WS, "ribosome")} == {c2.id}
    assert {c.id for c in conv_repo.search(OWNER, WS, "Alpha")} == {c1.id}


def test_message_list_order_recent_and_citations(db_session):
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)
    c = _conv(conv_repo)
    a = msg_repo.add(Message(conversation_id=c.id, role="user", content="first"))
    b = msg_repo.add(Message(conversation_id=c.id, role="assistant", content="second"))
    msg_repo.add_citations([MessageCitation(message_id=b.id, workspace_id=WS, citation_text="cite")])

    items, total = msg_repo.list(c.id)
    assert total == 2 and [m.content for m in items] == ["first", "second"]
    assert [m.id for m in msg_repo.recent(c.id, limit=1)] == [b.id]
    cits = msg_repo.citations_for([a.id, b.id])
    assert b.id in cits and a.id not in cits


def test_delete_for_conversation_purges_messages_and_citations(db_session):
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)
    c = _conv(conv_repo)
    m = msg_repo.add(Message(conversation_id=c.id, role="assistant", content="x"))
    msg_repo.add_citations([MessageCitation(message_id=m.id, workspace_id=WS, citation_text="c")])
    msg_repo.delete_for_conversation(c.id)
    assert msg_repo.list(c.id)[1] == 0
    assert msg_repo.citations_for([m.id]) == {}
