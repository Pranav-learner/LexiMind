"""Integration tests for the flashcards HTTP surface (inline runner + fake engine).

Exercises the full learning loop: generate deck → cards + citations persisted → review queue →
submit SM-2 reviews → analytics update, plus deck/card CRUD, conversions, export, and scoping.
"""

from __future__ import annotations


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/decks").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.post(f"/workspaces/{ws}/decks", json={"name": "x"}, headers=bob).status_code == 404


# ------------------------------------------------------------------ deck CRUD
def test_create_and_list_deck(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/decks", json={"name": "Biology", "color": "#10b981"}, headers=headers)
    assert r.status_code == 201 and r.json()["name"] == "Biology"
    lst = client.get(f"/workspaces/{ws}/decks", headers=headers).json()
    assert lst["total"] == 1 and lst["items"][0]["stats"]["total"] == 0


# ------------------------------------------------------------------ AI generation (async, inline)
def test_generate_deck_produces_cards_and_citations(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/decks/generate", json={"scope": "workspace", "count": 8}, headers=headers)
    assert r.status_code == 202
    did = r.json()["id"]
    assert r.json()["created_by"] == "ai"

    st = client.get(f"/workspaces/{ws}/decks/{did}/status", headers=headers).json()
    assert st["status"] == "completed" and st["card_count"] == 8

    cards = client.get(f"/workspaces/{ws}/flashcards?deck_id={did}", headers=headers).json()
    assert cards["total"] == 8
    detail = client.get(f"/workspaces/{ws}/flashcards/{cards['items'][0]['id']}", headers=headers).json()
    assert detail["citations"][0]["page_number"] >= 1

    # Workspace flashcard_count reflects the generated batch.
    assert client.get(f"/workspaces/{ws}", headers=headers).json()["flashcard_count"] == 8


def test_generate_validation_error(workspace):
    client, headers, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/decks/generate", json={"scope": "document"}, headers=headers).status_code == 422
    assert client.post(f"/workspaces/{ws}/decks/generate", json={"count": 999}, headers=headers).status_code == 422


# ------------------------------------------------------------------ manual card CRUD
def test_create_update_suspend_delete_card(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/flashcards", json={"front": "What is RAM?", "back": "Volatile memory."}, headers=headers)
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["learning_stage"] == "new"

    upd = client.patch(f"/workspaces/{ws}/flashcards/{cid}", json={"hint": "temporary"}, headers=headers)
    assert upd.json()["hint"] == "temporary"

    assert client.post(f"/workspaces/{ws}/flashcards/{cid}/suspend", headers=headers).json()["status"] == "suspended"
    assert client.post(f"/workspaces/{ws}/flashcards/{cid}/unsuspend", headers=headers).json()["status"] == "active"
    assert client.delete(f"/workspaces/{ws}/flashcards/{cid}", headers=headers).status_code == 204


def test_card_content_validation(workspace):
    client, headers, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/flashcards", json={"front": "", "back": "x"}, headers=headers).status_code == 422
    assert client.post(f"/workspaces/{ws}/flashcards", json={"front": "Q", "card_type": "basic"}, headers=headers).status_code == 422


# ------------------------------------------------------------------ review loop (SRS)
def test_review_queue_and_submit(workspace):
    client, headers, _, ws = workspace
    did = client.post(f"/workspaces/{ws}/decks/generate", json={"scope": "workspace", "count": 3}, headers=headers).json()["id"]

    q = client.get(f"/workspaces/{ws}/review?deck_id={did}", headers=headers).json()
    assert q["total_due"] == 3 and q["new_count"] == 3
    first = q["cards"][0]
    # Each card advertises the interval every button would schedule.
    ratings = {b["rating"]: b["interval_days"] for b in first["buttons"]}
    assert set(ratings) == {"again", "hard", "good", "easy"} and ratings["easy"] >= ratings["good"]

    cid = first["card"]["id"]
    res = client.post(f"/workspaces/{ws}/flashcards/{cid}/review", json={"rating": "good", "response_time_ms": 1200}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["scheduled_interval"] == 1 and body["card"]["review_count"] == 1

    # The reviewed card is no longer "new"; queue new_count drops.
    q2 = client.get(f"/workspaces/{ws}/review?deck_id={did}", headers=headers).json()
    assert q2["new_count"] == 2


def test_review_invalid_rating(workspace):
    client, headers, _, ws = workspace
    cid = client.post(f"/workspaces/{ws}/flashcards", json={"front": "Q", "back": "A"}, headers=headers).json()["id"]
    assert client.post(f"/workspaces/{ws}/flashcards/{cid}/review", json={"rating": "later"}, headers=headers).status_code == 422


# ------------------------------------------------------------------ analytics
def test_analytics_after_reviews(workspace):
    client, headers, _, ws = workspace
    c1 = client.post(f"/workspaces/{ws}/flashcards", json={"front": "Q1", "back": "A1"}, headers=headers).json()["id"]
    c2 = client.post(f"/workspaces/{ws}/flashcards", json={"front": "Q2", "back": "A2"}, headers=headers).json()["id"]
    client.post(f"/workspaces/{ws}/flashcards/{c1}/review", json={"rating": "good"}, headers=headers)
    client.post(f"/workspaces/{ws}/flashcards/{c2}/review", json={"rating": "again"}, headers=headers)
    an = client.get(f"/workspaces/{ws}/analytics", headers=headers).json()
    assert an["total_cards"] == 2 and an["reviews_total"] == 2 and an["accuracy"] == 0.5
    assert an["study_streak_days"] == 1 and len(an["daily_activity"]) == 30


# ------------------------------------------------------------------ export
def test_export_deck_csv_and_md(workspace):
    client, headers, _, ws = workspace
    did = client.post(f"/workspaces/{ws}/decks", json={"name": "Export"}, headers=headers).json()["id"]
    client.post(f"/workspaces/{ws}/flashcards", json={"deck_id": did, "front": "Q?", "back": "A", "hint": "h"}, headers=headers)
    csv_resp = client.get(f"/workspaces/{ws}/decks/{did}/export?format=csv", headers=headers)
    assert csv_resp.status_code == 200 and "text/csv" in csv_resp.headers["content-type"]
    assert "front,back,hint,card_type" in csv_resp.text and "Q?" in csv_resp.text
    md_resp = client.get(f"/workspaces/{ws}/decks/{did}/export?format=md", headers=headers)
    assert "# Export" in md_resp.text and "### Q?" in md_resp.text


def test_import_cards(workspace):
    client, headers, _, ws = workspace
    did = client.post(f"/workspaces/{ws}/decks", json={"name": "Import"}, headers=headers).json()["id"]
    text = "What is X?|X is a thing|hint one\nWhat is Y?|Y is another"
    r = client.post(f"/workspaces/{ws}/decks/{did}/import", json={"text": text}, headers=headers)
    assert r.status_code == 200
    assert client.get(f"/workspaces/{ws}/flashcards?deck_id={did}", headers=headers).json()["total"] == 2


# ------------------------------------------------------------------ conversions + regenerate/cancel
def test_generate_from_note_and_regenerate(workspace):
    client, headers, _, ws = workspace
    # Make a note first (Module 6), then a deck from it.
    note = client.post(f"/workspaces/{ws}/notes", json={"title": "N", "content": "body"}, headers=headers).json()
    r = client.post(f"/workspaces/{ws}/decks/from-note/{note['id']}?count=4", headers=headers)
    assert r.status_code == 202
    did = r.json()["id"]
    assert r.json()["note_id"] == note["id"]
    assert client.get(f"/workspaces/{ws}/decks/{did}/status", headers=headers).json()["card_count"] == 4

    regen = client.post(f"/workspaces/{ws}/decks/{did}/regenerate?count=6", headers=headers)
    assert regen.status_code == 200
    assert client.get(f"/workspaces/{ws}/decks/{did}/status", headers=headers).json()["card_count"] == 6

    # Cancelling a completed deck is a 409.
    assert client.post(f"/workspaces/{ws}/decks/{did}/cancel", headers=headers).status_code == 409
