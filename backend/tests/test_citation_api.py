"""Integration tests for the Citation Intelligence HTTP surface.

Generates real citations across chat, summaries, notes, and flashcards (via the fake engines), then
verifies the derived index unifies them and powers the panel, explorer, explain, search, and stats.
"""

from __future__ import annotations


def _seed_all(client, headers, ws):
    """Create a summary, a note, a flashcard deck, and a chat message — all citing doc_x chunks."""
    client.post(f"/workspaces/{ws}/summaries", json={"summary_type": "standard"}, headers=headers)
    client.post(f"/workspaces/{ws}/notes/generate", json={"note_type": "study"}, headers=headers)
    client.post(f"/workspaces/{ws}/decks/generate", json={"scope": "workspace", "count": 3}, headers=headers)
    conv = client.post(f"/workspaces/{ws}/conversations", json={"title": "Chat"}, headers=headers).json()
    client.post(f"/workspaces/{ws}/conversations/{conv['id']}/messages", json={"content": "What is virtual memory?"}, headers=headers)


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/citations").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.get(f"/workspaces/{ws}/citations", headers=bob).status_code == 404


# ------------------------------------------------------------------ index builds transparently
def test_index_aggregates_across_modules(workspace):
    client, headers, _, ws = workspace
    _seed_all(client, headers, ws)
    res = client.get(f"/workspaces/{ws}/citations", headers=headers).json()
    # doc_x:0 (shared by summary+note+flashcard+chat) and doc_x:9 (summary+note) at minimum.
    assert res["total"] >= 2
    chunk_ids = {c["chunk_id"] for c in res["items"]}
    assert "doc_x:0" in chunk_ids


def test_empty_workspace_has_no_citations(workspace):
    client, headers, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/citations", headers=headers).json()["total"] == 0


# ------------------------------------------------------------------ by-chunk detail + references
def test_by_chunk_detail_unifies_reference_types(workspace):
    client, headers, _, ws = workspace
    _seed_all(client, headers, ws)
    d = client.get(f"/workspaces/{ws}/citations/by-chunk?chunk_id=doc_x:0", headers=headers)
    assert d.status_code == 200
    body = d.json()
    # doc_x:0 is cited by a summary, a note, a flashcard, and a chat message.
    assert body["reference_count"] >= 4
    by_type = body["references_by_type"]
    assert by_type.get("summary") and by_type.get("note") and by_type.get("flashcard") and by_type.get("message")
    assert body["document"]["document_id"] == "doc_x"
    assert len(body["references"]) >= 4


# ------------------------------------------------------------------ knowledge explorer
def test_related_knowledge_backlinks(workspace):
    client, headers, _, ws = workspace
    _seed_all(client, headers, ws)
    cid = client.get(f"/workspaces/{ws}/citations/by-chunk?chunk_id=doc_x:0", headers=headers).json()["id"]
    rel = client.get(f"/workspaces/{ws}/citations/{cid}/related", headers=headers).json()
    # doc_x:0 co-occurs with doc_x:9 (same summary + same note) → a related edge exists.
    rel_chunks = {r["chunk_id"] for r in rel["related"]}
    assert "doc_x:9" in rel_chunks
    assert any(r["relationship"] == "co_reference" for r in rel["related"])
    # Same-document citations surfaced too.
    assert isinstance(rel["same_document_citations"], list)
    assert rel["references_by_type"].get("summary")


# ------------------------------------------------------------------ explain
def test_explain_citation(workspace):
    client, headers, _, ws = workspace
    _seed_all(client, headers, ws)
    cid = client.get(f"/workspaces/{ws}/citations/by-chunk?chunk_id=doc_x:0", headers=headers).json()["id"]
    ex = client.get(f"/workspaces/{ws}/citations/{cid}/explain", headers=headers).json()
    assert "confidence" in ex["summary"].lower() or "evidence" in ex["summary"].lower()
    assert len(ex["factors"]) >= 2
    assert len(ex["retrieval_path"]) == 7          # the fixed Phase 1+2 pipeline
    assert any("Corroboration" == f["label"] for f in ex["factors"])  # reused across assets


# ------------------------------------------------------------------ search + filters
def test_search_by_keyword_and_type(workspace):
    client, headers, _, ws = workspace
    _seed_all(client, headers, ws)
    # Keyword search over citation text.
    kw = client.get(f"/workspaces/{ws}/citations?keyword=evidence", headers=headers).json()
    assert kw["total"] >= 1
    # Filter to citations referenced by a flashcard.
    fc = client.get(f"/workspaces/{ws}/citations?reference_type=flashcard", headers=headers).json()
    assert fc["total"] >= 1
    # High-confidence filter.
    hc = client.get(f"/workspaces/{ws}/citations?min_confidence=0.5", headers=headers).json()
    assert hc["total"] >= 1


# ------------------------------------------------------------------ stats
def test_citation_stats(workspace):
    client, headers, _, ws = workspace
    _seed_all(client, headers, ws)
    s = client.get(f"/workspaces/{ws}/citations/stats", headers=headers).json()
    assert s["total_citations"] >= 2 and s["total_references"] >= 6
    assert s["documents_cited"] >= 1
    assert s["references_by_type"]["note"] >= 1 and s["references_by_type"]["message"] >= 1
    assert len(s["most_referenced"]) >= 1


# ------------------------------------------------------------------ reindex + freshness
def test_reindex_and_incremental_freshness(workspace):
    client, headers, _, ws = workspace
    client.post(f"/workspaces/{ws}/notes/generate", json={"note_type": "study"}, headers=headers)
    before = client.get(f"/workspaces/{ws}/citations", headers=headers).json()["total"]
    # Add more citations (a summary) → the next read transparently re-syncs.
    client.post(f"/workspaces/{ws}/summaries", json={"summary_type": "standard"}, headers=headers)
    after = client.get(f"/workspaces/{ws}/citations", headers=headers).json()["total"]
    assert after >= before
    # Manual reindex endpoint works.
    r = client.post(f"/workspaces/{ws}/citations/reindex", headers=headers)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_missing_citation_404(workspace):
    client, headers, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/citations/cite_nope", headers=headers).status_code == 404
    assert client.get(f"/workspaces/{ws}/citations/by-chunk?chunk_id=nope", headers=headers).status_code == 404
