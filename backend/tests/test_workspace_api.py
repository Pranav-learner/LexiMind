"""Integration tests for the workspace + auth HTTP layer (TestClient over a minimal app).

Covers the full lifecycle create -> edit -> archive -> restore -> delete, plus auth
enforcement, validation error mapping, and cross-user isolation.
"""


def test_auth_required(client):
    assert client.get("/workspaces").status_code == 401
    assert client.post("/workspaces", json={"name": "X"}).status_code == 401


def test_full_lifecycle(auth):
    client, headers, _ = auth

    # create
    r = client.post(
        "/workspaces",
        headers=headers,
        json={"name": "Operating Systems", "description": "kernels", "icon": "🧠", "color": "#112233"},
    )
    assert r.status_code == 201, r.text
    ws = r.json()
    wid = ws["id"]
    assert ws["name"] == "Operating Systems"
    assert ws["is_archived"] is False

    # get
    assert client.get(f"/workspaces/{wid}", headers=headers).json()["id"] == wid

    # list (active)
    listing = client.get("/workspaces", headers=headers).json()
    assert listing["total"] == 1 and listing["pages"] == 1

    # edit (rename + description)
    r = client.patch(
        f"/workspaces/{wid}", headers=headers, json={"name": "OS", "description": "updated"}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "OS" and r.json()["description"] == "updated"

    # archive -> disappears from active list, appears in archived list
    assert client.post(f"/workspaces/{wid}/archive", headers=headers).json()["is_archived"] is True
    assert client.get("/workspaces", headers=headers).json()["total"] == 0
    assert client.get("/workspaces?archived=archived", headers=headers).json()["total"] == 1

    # restore
    assert client.post(f"/workspaces/{wid}/restore", headers=headers).json()["is_archived"] is False
    assert client.get("/workspaces", headers=headers).json()["total"] == 1

    # soft delete -> gone from all listings, 404 on get
    assert client.delete(f"/workspaces/{wid}", headers=headers).status_code == 204
    assert client.get("/workspaces?archived=all", headers=headers).json()["total"] == 0
    assert client.get(f"/workspaces/{wid}", headers=headers).status_code == 404


def test_duplicate_name_conflict(auth):
    client, headers, _ = auth
    client.post("/workspaces", headers=headers, json={"name": "Dup"})
    r = client.post("/workspaces", headers=headers, json={"name": "dup"})
    assert r.status_code == 409


def test_invalid_name_returns_422(auth):
    client, headers, _ = auth
    r = client.post("/workspaces", headers=headers, json={"name": "bad/name"})
    assert r.status_code == 422


def test_cross_user_isolation(client):
    a = client.post(
        "/auth/register", json={"email": "a@x.com", "password": "password123"}
    ).json()
    b = client.post(
        "/auth/register", json={"email": "b@x.com", "password": "password123"}
    ).json()
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}

    wid = client.post("/workspaces", headers=ha, json={"name": "Alice WS"}).json()["id"]
    # Bob cannot see or fetch Alice's workspace.
    assert client.get("/workspaces", headers=hb).json()["total"] == 0
    assert client.get(f"/workspaces/{wid}", headers=hb).status_code == 404
    # Both can independently reuse the same workspace name (unique per owner).
    assert client.post("/workspaces", headers=hb, json={"name": "Alice WS"}).status_code == 201


def test_pagination_and_search(auth):
    client, headers, _ = auth
    for i in range(15):
        client.post("/workspaces", headers=headers, json={"name": f"Space {i:02d}"})
    page1 = client.get("/workspaces?page=1&page_size=10", headers=headers).json()
    assert page1["total"] == 15 and len(page1["items"]) == 10 and page1["pages"] == 2
    found = client.get("/workspaces?search=Space 07", headers=headers).json()
    assert found["total"] == 1 and found["items"][0]["name"] == "Space 07"
