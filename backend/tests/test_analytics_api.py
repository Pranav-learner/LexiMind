"""Integration tests for the Knowledge Dashboard & Analytics HTTP surface.

Seeds a full workspace (document + chat + summary + note + flashcards + reviews) via the real
endpoints, then verifies the dashboard aggregates everything, insights fire, and charts/timeline
render.
"""

from __future__ import annotations


def _upload(client, headers, ws, name="OS.pdf"):
    return client.post(f"/workspaces/{ws}/documents",
                       files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))], headers=headers)


def _seed(client, headers, ws):
    _upload(client, headers, ws)
    doc_id = client.get(f"/workspaces/{ws}/documents", headers=headers).json()["items"][0]["id"]
    # Scope the summary + note to the document so per-document analytics link up.
    client.post(f"/workspaces/{ws}/summaries", json={"summary_type": "standard", "scope": "document", "document_id": doc_id}, headers=headers)
    client.post(f"/workspaces/{ws}/notes/generate", json={"note_type": "study", "scope": "document", "document_id": doc_id}, headers=headers)
    did = client.post(f"/workspaces/{ws}/decks/generate", json={"scope": "workspace", "count": 4}, headers=headers).json()["id"]
    conv = client.post(f"/workspaces/{ws}/conversations", json={"title": "Chat"}, headers=headers).json()
    client.post(f"/workspaces/{ws}/conversations/{conv['id']}/messages", json={"content": "What is virtual memory?"}, headers=headers)
    # Review a couple of cards so learning analytics + reviews have data.
    q = client.get(f"/workspaces/{ws}/review?deck_id={did}", headers=headers).json()
    for rc in q["cards"][:2]:
        client.post(f"/workspaces/{ws}/flashcards/{rc['card']['id']}/review", json={"rating": "good"}, headers=headers)
    return did


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/dashboard").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.get(f"/workspaces/{ws}/dashboard", headers=bob).status_code == 404


# ------------------------------------------------------------------ full dashboard
def test_dashboard_aggregates_everything(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    d = client.get(f"/workspaces/{ws}/dashboard", headers=headers).json()

    assert d["knowledge"]["documents"] == 1
    assert d["knowledge"]["chunks"] >= 1 and d["knowledge"]["embeddings"] == d["knowledge"]["chunks"]
    assert d["ai_usage"]["conversations"] == 1 and d["ai_usage"]["questions_asked"] == 1
    assert d["ai_usage"]["summaries_generated"] == 1 and d["ai_usage"]["notes_generated"] == 1
    assert d["ai_usage"]["flashcards_generated"] == 4
    assert d["learning"]["cards_reviewed"] == 2
    assert d["retrieval"]["reranker_enabled"] in (True, False)
    assert "series" in d["charts"] and len(d["charts"]["series"]) >= 5
    assert isinstance(d["activity"], dict) and len(d["activity"]["items"]) >= 4
    assert isinstance(d["insights"], list)


def test_empty_workspace_dashboard(workspace):
    client, headers, _, ws = workspace
    d = client.get(f"/workspaces/{ws}/dashboard", headers=headers).json()
    assert d["knowledge"]["documents"] == 0
    assert d["ai_usage"]["messages"] == 0
    assert d["learning"]["cards_reviewed"] == 0


# ------------------------------------------------------------------ sections
def test_individual_sections(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    assert client.get(f"/workspaces/{ws}/dashboard/knowledge", headers=headers).json()["documents"] == 1
    assert client.get(f"/workspaces/{ws}/dashboard/ai-usage", headers=headers).json()["messages"] >= 1
    assert client.get(f"/workspaces/{ws}/dashboard/learning", headers=headers).json()["cards_reviewed"] == 2
    r = client.get(f"/workspaces/{ws}/dashboard/retrieval", headers=headers).json()
    assert r["dense_top_k"] >= 1 and "note" in r
    ch = client.get(f"/workspaces/{ws}/dashboard/charts", headers=headers).json()
    assert any(s["kind"] == "heatmap" for s in ch["series"])
    assert any(s["kind"] == "donut" for s in ch["series"])


# ------------------------------------------------------------------ documents analytics
def test_document_analytics(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    docs = client.get(f"/workspaces/{ws}/dashboard/documents", headers=headers).json()["items"]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["chunks"] >= 1 and doc["summaries"] == 1 and doc["notes"] == 1
    # Single-document endpoint.
    one = client.get(f"/workspaces/{ws}/dashboard/documents/{doc['id']}", headers=headers)
    assert one.status_code == 200 and one.json()["id"] == doc["id"]
    assert client.get(f"/workspaces/{ws}/dashboard/documents/nope", headers=headers).status_code == 404


# ------------------------------------------------------------------ activity + insights
def test_activity_timeline_and_filter(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    all_ev = client.get(f"/workspaces/{ws}/dashboard/activity", headers=headers).json()["items"]
    types = {e["type"] for e in all_ev}
    assert {"document", "summary", "note", "chat", "deck"} & types
    docs_only = client.get(f"/workspaces/{ws}/dashboard/activity?type=document", headers=headers).json()["items"]
    assert all(e["type"] == "document" for e in docs_only)


def test_insights_generated(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    ins = client.get(f"/workspaces/{ws}/dashboard/insights", headers=headers).json()["items"]
    assert len(ins) >= 1
    assert all("severity" in i and "title" in i for i in ins)


# ------------------------------------------------------------------ caching + refresh
def test_cache_and_refresh(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    before = client.get(f"/workspaces/{ws}/dashboard/knowledge", headers=headers).json()["documents"]
    assert before == 1
    _upload(client, headers, ws, name="Networking.pdf")  # add a second document → signature changes
    after = client.get(f"/workspaces/{ws}/dashboard/knowledge", headers=headers).json()["documents"]
    assert after == 2  # cache transparently invalidated by the signature
    # Manual refresh returns a full dashboard.
    refreshed = client.post(f"/workspaces/{ws}/dashboard/refresh", headers=headers).json()
    assert refreshed["knowledge"]["documents"] == 2
