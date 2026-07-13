"""Declarative Policy Engine.

Evaluates security and AI governance policies (temporal windows, IP restrictions,
allowed models, and quotas) against incoming requests.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, time, timezone
from sqlalchemy.orm import Session

from app.security.errors import PolicyDenyError
from app.security.models import SecurityPolicy


def is_ip_allowed(client_ip: str, allow_list: list[str] | None, deny_list: list[str] | None) -> bool:
    """Validate client IP against declarative allow and deny CIDR/IP lists."""
    if not client_ip:
        # If policy specifies IP limits but client IP is unknown, deny access
        return not (allow_list or deny_list)

    try:
        client_addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False  # Malformed IP address is rejected

    if deny_list:
        for deny_cidr in deny_list:
            try:
                if client_addr in ipaddress.ip_network(deny_cidr, strict=False):
                    return False
            except ValueError:
                continue

    if allow_list:
        allowed = False
        for allow_cidr in allow_list:
            try:
                if client_addr in ipaddress.ip_network(allow_cidr, strict=False):
                    allowed = True
                    break
            except ValueError:
                continue
        if not allowed:
            return False

    return True


def is_time_allowed(current_dt: datetime, time_windows: list[dict]) -> bool:
    """Verify if the request occurs within permitted time windows (HH:MM bounds)."""
    if not time_windows:
        return True

    # Normalize to weekday (Monday = 1, Sunday = 7)
    weekday = current_dt.isoweekday()
    req_time = current_dt.time()

    for window in time_windows:
        # Check day-of-week constraint if specified
        days = window.get("days")
        if days and weekday not in days:
            continue

        try:
            start_str = window.get("start", "00:00")
            end_str = window.get("end", "23:59")
            
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))

            start_t = time(sh, sm)
            end_t = time(eh, em)

            if start_t <= req_time <= end_t:
                return True
        except (ValueError, TypeError):
            continue

    return False


def evaluate_policies(
    db: Session,
    actor_id: str,
    action: str,
    workspace_id: str | None = None,
    organization_id: str | None = None,
    ip_address: str | None = None,
    current_dt: datetime | None = None,
    model_name: str | None = None,
    tokens_requested: int | None = None,
) -> dict:
    """Evaluate all active policies applicable to the current scope.

    Raises:
        PolicyDenyError: If any declarative policy rules trigger a deny decision.
    """
    if not current_dt:
        current_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    # Fetch active policies across hierarchy: Global -> Organization -> Workspace
    query = db.query(SecurityPolicy).filter(SecurityPolicy.is_active.is_(True))
    
    # SQLite compatibility for multiple filters
    policies = query.all()
    applicable_policies = []
    
    for p in policies:
        # A policy is applicable if:
        # - It matches the workspace_id
        # - It matches the organization_id (and is not workspace specific)
        # - It is global (both org and ws are null)
        if p.workspace_id and p.workspace_id == workspace_id:
            applicable_policies.append(p)
        elif p.organization_id and p.organization_id == organization_id and not p.workspace_id:
            applicable_policies.append(p)
        elif not p.organization_id and not p.workspace_id:
            applicable_policies.append(p)

    decisions = []

    for policy in applicable_policies:
        rules = policy.rules or {}
        policy_decision = {"policy_id": policy.id, "name": policy.name, "status": "allow"}

        # 1. IP Restrictions Check
        allow_ips = rules.get("allow_ips")
        deny_ips = rules.get("deny_ips")
        if allow_ips or deny_ips:
            if not is_ip_allowed(ip_address or "", allow_ips, deny_ips):
                policy_decision["status"] = "deny"
                policy_decision["reason"] = f"IP '{ip_address}' is blocked by policy: {policy.name}."
                decisions.append(policy_decision)
                raise PolicyDenyError(policy_decision["reason"])

        # 2. Temporal / Access Windows Check
        time_windows = rules.get("time_windows")
        if time_windows:
            if not is_time_allowed(current_dt, time_windows):
                policy_decision["status"] = "deny"
                policy_decision["reason"] = f"Request time {current_dt.strftime('%H:%M')} falls outside permitted windows for policy: {policy.name}."
                decisions.append(policy_decision)
                raise PolicyDenyError(policy_decision["reason"])

        # 3. AI Governance Models & Quotas
        ai_gov = rules.get("ai_governance")
        if ai_gov and action.startswith("agent."):
            allowed_models = ai_gov.get("allowed_models")
            if model_name and allowed_models and model_name not in allowed_models:
                policy_decision["status"] = "deny"
                policy_decision["reason"] = f"Model '{model_name}' is not allowed under policy: {policy.name}."
                decisions.append(policy_decision)
                raise PolicyDenyError(policy_decision["reason"])

            max_tokens = ai_gov.get("max_tokens_per_request")
            if tokens_requested and max_tokens and tokens_requested > max_tokens:
                policy_decision["status"] = "deny"
                policy_decision["reason"] = f"Requested tokens ({tokens_requested}) exceed limit ({max_tokens}) of policy: {policy.name}."
                decisions.append(policy_decision)
                raise PolicyDenyError(policy_decision["reason"])

        decisions.append(policy_decision)

    return {"status": "allow", "evaluations": decisions}
