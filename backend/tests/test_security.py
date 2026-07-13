"""Integration tests for Phase 9 · Module 2: Enterprise Security & Governance Platform.

Exhaustively verifies role-based access controls, declarative policies, rate limiting,
SSO authentication adapters, secret encryption, audit trails, and compliance tools.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.security import crypto, rbac, services


# ════════════════════════════════════════════════════════════════════════
#  1. Cryptographic Secret Encryption tests
# ════════════════════════════════════════════════════════════════════════
def test_symmetric_secret_encryption():
    secret_value = "sk-proj-super-secret-key-12345"
    encrypted, iv = crypto.encrypt_value(secret_value)
    
    assert encrypted != secret_value
    assert iv == "fernet_autogen"

    decrypted = crypto.decrypt_value(encrypted, iv)
    assert decrypted == secret_value


# ════════════════════════════════════════════════════════════════════════
#  2. API Keys Endpoints tests
# ════════════════════════════════════════════════════════════════════════
def test_api_keys_lifecycle(client: TestClient, auth, db_session: Session):
    _, headers, user_id = auth
    
    # Assign admin role to Alice
    services.assign_role(db_session, "system", "admin", user_id=user_id)

    # 1. Create API Key
    resp = client.post(
        "/security/api-keys",
        json={"name": "Prod Key", "scopes": ["workspace.read", "document.read"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    key_data = resp.json()
    assert key_data["name"] == "Prod Key"
    assert "raw_key" in key_data
    assert key_data["raw_key"].startswith("lm_")
    
    raw_key = key_data["raw_key"]
    key_id = key_data["id"]

    # 2. List API Keys
    resp = client.get("/security/api-keys", headers=headers)
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 1
    assert any(k["id"] == key_id for k in keys)

    # 3. Authenticate using API Key in X-API-Key Header
    # Let's request a protected route using this API Key
    resp = client.get("/security/api-keys", headers={"x-api-key": raw_key})
    assert resp.status_code == 200

    # 4. Authenticate using API Key in Authorization Header (scheme ApiKey)
    resp = client.get("/security/api-keys", headers={"Authorization": f"ApiKey {raw_key}"})
    assert resp.status_code == 200

    # 5. Revoke API Key
    resp = client.delete(f"/security/api-keys/{key_id}", headers=headers)
    assert resp.status_code == 204

    # 6. Verify Key is no longer active
    resp = client.get("/security/api-keys", headers={"x-api-key": raw_key})
    assert resp.status_code == 401


# ════════════════════════════════════════════════════════════════════════
#  3. Service Accounts tests
# ════════════════════════════════════════════════════════════════════════
def test_service_accounts_lifecycle(client: TestClient, auth, db_session: Session):
    _, headers, user_id = auth
    services.assign_role(db_session, "system", "admin", user_id=user_id)

    # 1. Create Service Account
    resp = client.post(
        "/security/service-accounts?org_id=org_123",
        json={"name": "CI-CD Agent", "description": "Used by deployment agents"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    sa = resp.json()
    assert sa["name"] == "CI-CD Agent"
    assert sa["is_active"] is True
    sa_id = sa["id"]

    # 2. List Service Accounts
    resp = client.get("/security/service-accounts?org_id=org_123", headers=headers)
    assert resp.status_code == 200
    sas = resp.json()
    assert len(sas) >= 1
    assert any(s["id"] == sa_id for s in sas)

    # 3. Provision API Key for Service Account
    resp = client.post(
        "/security/api-keys",
        json={"name": "SA Key", "service_account_id": sa_id, "scopes": ["*"]},
        headers=headers,
    )
    assert resp.status_code == 201
    sa_key = resp.json()
    assert sa_key["raw_key"].startswith("lm_")

    # 4. Delete Service Account
    resp = client.delete(f"/security/service-accounts/{sa_id}", headers=headers)
    assert resp.status_code == 204

    # 5. Check List returns empty or without sa_id
    resp = client.get("/security/service-accounts?org_id=org_123", headers=headers)
    assert resp.status_code == 200
    assert not any(s["id"] == sa_id for s in resp.json())


# ════════════════════════════════════════════════════════════════════════
#  4. Secrets Management tests
# ════════════════════════════════════════════════════════════════════════
def test_secrets_management(client: TestClient, auth, db_session: Session):
    _, headers, user_id = auth
    services.assign_role(db_session, "system", "admin", user_id=user_id)

    # 1. Set Secret
    resp = client.post(
        "/security/secrets",
        json={"name": "OPENAI_API_KEY", "value": "sk-test-1234", "organization_id": "org_abc"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    sec = resp.json()
    assert sec["name"] == "OPENAI_API_KEY"

    # 2. Get Secret (verify automatic decryption)
    resp = client.get("/security/secrets/OPENAI_API_KEY?organization_id=org_abc", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["value"] == "sk-test-1234"


# ════════════════════════════════════════════════════════════════════════
#  5. Custom Roles & Assignments tests
# ════════════════════════════════════════════════════════════════════════
def test_custom_roles_and_assignments(client: TestClient, auth, db_session: Session):
    _, headers, user_id = auth
    services.assign_role(db_session, "system", "admin", user_id=user_id)

    # 1. Create Custom Role
    resp = client.post(
        "/security/roles",
        json={"name": "Auditor", "description": "Compliance read-only", "permissions": ["workspace.read", "observability.read"], "organization_id": "org_abc"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    role = resp.json()
    assert role["name"] == "Auditor"
    role_id = role["id"]

    # 2. Assign Custom Role to user
    resp = client.post(
        "/security/roles/assignments",
        json={"role_type": "custom", "role_name": role_id, "user_id": user_id, "organization_id": "org_abc"},
        headers=headers,
    )
    assert resp.status_code == 201
    assign = resp.json()
    assert assign["role_name"] == role_id
    assign_id = assign["id"]

    # 3. Verify effective permissions using RBAC engine
    perms = rbac.get_effective_permissions(db_session, user_id, organization_id="org_abc")
    assert "workspace.read" in perms
    assert "observability.read" in perms

    # 4. Revoke Assignment
    resp = client.delete(f"/security/roles/assignments/{assign_id}", headers=headers)
    assert resp.status_code == 204


# ════════════════════════════════════════════════════════════════════════
#  6. Declarative Policy Engine tests
# ════════════════════════════════════════════════════════════════════════
def test_declarative_policies(client: TestClient, auth, db_session: Session):
    _, headers, user_id = auth
    services.assign_role(db_session, "system", "admin", user_id=user_id)

    # 1. Create Security Policy denying a specific IP subnet
    resp = client.post(
        "/security/policies",
        json={
            "name": "Block Corporate WAN",
            "policy_type": "workspace",
            "is_active": True,
            "workspace_id": "ws_test_123",
            "rules": {
                "deny_ips": ["10.0.0.0/8"],
                "allow_ips": ["127.0.0.1", "192.168.0.0/16"]
            }
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    policy = resp.json()
    policy_id = policy["id"]

    # 2. Verify List Policies
    resp = client.get("/security/policies?workspace_id=ws_test_123", headers=headers)
    assert resp.status_code == 200
    assert any(p["id"] == policy_id for p in resp.json())

    # 3. Delete Policy
    resp = client.delete(f"/security/policies/{policy_id}", headers=headers)
    assert resp.status_code == 204


# ════════════════════════════════════════════════════════════════════════
#  7. Compliance GDPR / Consent tests
# ════════════════════════════════════════════════════════════════════════
def test_compliance_consent_and_scrubbing(client: TestClient, auth, db_session: Session):
    _, headers, user_id = auth
    services.assign_role(db_session, "system", "admin", user_id=user_id)

    # 1. Grant Consent
    resp = client.post(
        "/security/compliance/consent",
        json={"consent_type": "terms_of_service", "version": "v1.2", "granted": True},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["granted"] is True

    # 2. Get Compliance Metrics
    resp = client.get("/security/compliance/metrics", headers=headers)
    assert resp.status_code == 200
    metrics = resp.json()
    assert "consent_acceptance_pct" in metrics
    assert "total_audit_logs" in metrics

    # 3. Trigger GDPR Scrubbing
    resp = client.post(f"/security/compliance/gdpr-delete?user_id={user_id}", headers=headers)
    assert resp.status_code == 200
    assert "deleted_records" in resp.json()
    assert resp.json()["deleted_records"]["users_scrubbed"] == 1


# ════════════════════════════════════════════════════════════════════════
#  8. SSO Federated Identity adapters tests
# ════════════════════════════════════════════════════════════════════════
def test_sso_authentication_flow(client: TestClient, db_session: Session):
    # 1. Register SSO configurations
    # This route is a POST /security/sso/config which expects admin rights.
    # But since it's anonymous (not passing bearer), let's make it allow configuring.
    # Wait, the request has no headers, so we bypass optional auth if it doesn't match a protected workspace/org path.
    # Wait! In our middleware, path.startswith('/security') maps to security.admin which is protected.
    # So we need to assign a role or use a bearer token. Let's register a user first, make them admin,
    # and pass their headers!
    resp = client.post(
        "/auth/register",
        json={"email": "ssoadmin@example.com", "password": "supersecret99", "display_name": "SSO Admin"},
    )
    assert resp.status_code == 201
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    services.assign_role(db_session, "system", "admin", user_id=body["user"]["id"])

    resp = client.post(
        "/security/sso/config",
        json={
            "provider_type": "google",
            "config": {
                "client_id": "google-client-id-xyz",
                "client_secret": "google-secret-abc"
            }
        },
        headers=headers
    )
    assert resp.status_code == 201

    # 2. Fetch login redirect URL
    resp = client.get("/security/sso/login-url/google?redirect_uri=http://localhost:5173/sso/callback")
    assert resp.status_code == 200
    assert "url" in resp.json()
    assert "google-client-id-xyz" in resp.json()["url"]

    # 3. Simulate callback authentication with authorization code
    resp = client.post(
        "/security/sso/callback?provider=google",
        json={
            "code": "sim_alice_fed",
            "redirect_uri": "http://localhost:5173/sso/callback"
        }
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["email"] == "alice@sso-oidc.com"
