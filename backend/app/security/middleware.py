"""FastAPI Zero Trust Security & Authorization Middleware.

Intercepts requests, extracts identity, resolves workspace/org contexts,
evaluates declarative policies, checks RBAC, and logs audit events.
"""

from __future__ import annotations

import re
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.db.base import SessionLocal
from app.security import rbac, services
from app.security.errors import SecurityException
from app.security.dependencies import resolve_actor_identity
from app.security.policy import evaluate_policies

# Patterns for resolving workspace_id and organization_id from path
WORKSPACE_PATH_RE = re.compile(r"/workspaces/([^/]+)")
ORGANIZATION_PATH_RE = re.compile(r"/collaboration/organizations/([^/]+)")


class SecurityAuthorizationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Bypass public paths
        path = request.url.path
        if path in {"/", "/health", "/auth/login", "/auth/register", "/docs", "/openapi.json"} or "/invitations/" in path:
            return await call_next(request)

        # 2. Check if route is protected (Zero Trust scope)
        if "/security/sso/login-url" in path or "/security/sso/callback" in path or "/access" in path:
            return await call_next(request)

        is_protected = any(
            path.startswith(prefix)
            for prefix in ["/workspaces", "/collaboration", "/security", "/governance"]
        )

        # 3. Retrieve database session (respecting dependency overrides for testing)
        from app.db.base import get_db
        db_override = request.app.dependency_overrides.get(get_db)
        db_gen = None
        if db_override:
            db_gen = db_override()
            db = next(db_gen)
        else:
            db = SessionLocal()

        try:
            # Extract credentials
            auth_header = request.headers.get("authorization")
            x_api_key = request.headers.get("x-api-key")

            actor = resolve_actor_identity(db, auth_header, x_api_key)

            if not actor:
                if is_protected:
                    # Log failure to console and deny
                    return JSONResponse(
                        status_code=401,
                        content={"code": "unauthorized", "message": "Authentication credentials required."},
                    )
                else:
                    # Bypass optional auth for backward compatibility
                    return await call_next(request)

            # Store actor on request state for use inside route handlers
            request.state.actor = actor

            # 4. Resolve Contexts
            workspace_id = None
            organization_id = None

            ws_match = WORKSPACE_PATH_RE.search(path)
            if ws_match:
                workspace_id = ws_match.group(1)

            org_match = ORGANIZATION_PATH_RE.search(path)
            if org_match:
                organization_id = org_match.group(1)

            # Validate resource existence to return 404 instead of 403 (Zero Trust Isolation)
            if workspace_id:
                from app.workspaces.models import Workspace
                ws = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.deleted_at.is_(None)).first()
                if not ws:
                    return JSONResponse(
                        status_code=404,
                        content={"code": "not_found", "message": "Workspace not found."},
                    )

            if organization_id:
                from app.collaboration.models import Organization
                org = db.query(Organization).filter(Organization.id == organization_id, Organization.deleted_at.is_(None)).first()
                if not org:
                    return JSONResponse(
                        status_code=404,
                        content={"code": "not_found", "message": "Organization not found."},
                    )

            # 5. Map Path & Method to Action Permission
            action = self._map_request_to_action(request.method, path)

            # 6. Execute Authorization Engine Checks
            # Check RBAC
            allowed = rbac.has_permission(
                db, actor["id"], action, workspace_id=workspace_id, organization_id=organization_id
            )

            # Record audit details
            ip_address = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            actor_email = actor.get("email")

            if not allowed:
                # Log Denied Event
                services.log_security_event(
                    db,
                    actor_type=actor["type"],
                    actor_id=actor["id"],
                    actor_email=actor_email,
                    action=action,
                    resource_type="request",
                    resource_id=path,
                    workspace_id=workspace_id,
                    organization_id=organization_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status="failure",
                    failure_reason="RBAC Permission Denied",
                )
                status_code = 403
                code = "forbidden"
                msg = f"Action '{action}' is forbidden."
                if (workspace_id or organization_id) and action.endswith(".read"):
                    status_code = 404
                    code = "not_found"
                    msg = "Resource not found."

                return JSONResponse(
                    status_code=status_code,
                    content={"code": code, "message": msg},
                )

            # Evaluate policies (IP, temporal, AI limits)
            # Fetch prompt metrics if checking agent runtimes
            tokens_req = None
            model_name = None
            if "agent" in path:
                try:
                    body = await request.json()
                    model_name = body.get("model_name")
                    tokens_req = body.get("max_tokens")
                except Exception:
                    pass

            try:
                policy_result = evaluate_policies(
                    db,
                    actor["id"],
                    action,
                    workspace_id=workspace_id,
                    organization_id=organization_id,
                    ip_address=ip_address,
                    model_name=model_name,
                    tokens_requested=tokens_req,
                )
            except SecurityException as e:
                services.log_security_event(
                    db,
                    actor_type=actor["type"],
                    actor_id=actor["id"],
                    actor_email=actor_email,
                    action=action,
                    resource_type="request",
                    resource_id=path,
                    workspace_id=workspace_id,
                    organization_id=organization_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status="failure",
                    failure_reason=str(e),
                )
                return JSONResponse(
                    status_code=e.status_code,
                    content={"code": e.code, "message": str(e)},
                )

            # Log Authorized Access Success
            services.log_security_event(
                db,
                actor_type=actor["type"],
                actor_id=actor["id"],
                actor_email=actor_email,
                action=action,
                resource_type="request",
                resource_id=path,
                workspace_id=workspace_id,
                organization_id=organization_id,
                ip_address=ip_address,
                user_agent=user_agent,
                status="success",
                policy_decisions=policy_result,
            )

        finally:
            if db_gen:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
            else:
                db.close()

        # Proceed with request pipeline
        return await call_next(request)

    def _map_request_to_action(self, method: str, path: str) -> str:
        """Map standard path scopes to resource actions."""
        # Clean paths for matching
        m_lower = method.lower()
        
        # Admin paths
        if path.startswith("/security") or path.startswith("/governance"):
            return "security.admin"

        # Collaboration specific operations (comments, presence, activity feed, sync, versions) map to workspace.read
        if any(keyword in path for keyword in ["comments", "presence", "activity", "sync", "versions"]):
            return "workspace.read"

        # Check resource category
        category = "workspace"
        if "documents" in path:
            category = "document"
        elif "conversations" in path:
            category = "chat"
        elif "notes" in path or "tags" in path:
            category = "note"
        elif "graph" in path:
            category = "graph"
        elif "agents" in path:
            category = "agent"
        elif "organizations" in path:
            category = "org"

        # Map action verb
        verb = "read"
        if m_lower in {"post", "put", "patch"}:
            verb = "write"
            if m_lower == "post" and category == "agent" and "execute" in path:
                verb = "execute"
        elif m_lower == "delete":
            verb = "delete"

        return f"{category}.{verb}"
