import { apiRequest } from "./client";

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  expires_at: string | null;
  is_active: boolean;
}

export interface CustomRole {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
}

export interface SSOConfig {
  provider_type: string;
  client_id: string;
  issuer_url: string | null;
  entry_point: string | null;
  is_active: boolean;
}

export interface AuditLog {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string;
  actor_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
  workspace_id: string | null;
  organization_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  status: string;
  failure_reason: string | null;
  timestamp: string;
}

export interface AuditLogsResponse {
  logs: AuditLog[];
  total: number;
}

export function getKeys() {
  return apiRequest<ApiKey[]>("/security/keys");
}

export function createKey(name: string, expiresInSeconds: number | null) {
  return apiRequest<ApiKey & { key?: string }>("/security/keys", {
    method: "POST",
    body: { name, expires_in_seconds: expiresInSeconds },
  });
}

export function revokeKey(keyId: string) {
  return apiRequest<void>(`/security/keys/${keyId}`, { method: "DELETE" });
}

export function getSSOConfig() {
  return apiRequest<SSOConfig | null>("/security/sso/config");
}

export function saveSSOConfig(config: Partial<SSOConfig> & { client_secret?: string; x509_cert?: string }) {
  return apiRequest<SSOConfig>("/security/sso/config", {
    method: "POST",
    body: config,
  });
}

export function getCustomRoles() {
  return apiRequest<CustomRole[]>("/security/roles");
}

export function createCustomRole(role: CustomRole) {
  return apiRequest<CustomRole>("/security/roles", {
    method: "POST",
    body: role,
  });
}

export function deleteCustomRole(roleId: string) {
  return apiRequest<void>(`/security/roles/${roleId}`, { method: "DELETE" });
}

export function getAuditLogs(params: {
  workspace_id?: string;
  organization_id?: string;
  actor_id?: string;
  action?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      q.set(k, String(v));
    }
  });
  return apiRequest<AuditLogsResponse>(`/security/audit?${q.toString()}`);
}

export function scrubUserData(userId: string) {
  return apiRequest<{ message: string; scrubbing_task_id: string }>("/security/gdpr/scrub", {
    method: "POST",
    body: { user_id: userId },
  });
}
