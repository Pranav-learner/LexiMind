import { useEffect, useState, useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/security";
import * as wsApi from "../api/workspaces";
import { ApiError } from "../api/client";
import type { Workspace } from "../types";

export default function SecurityWorkspace() {
  const { workspaceId = "" } = useParams();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [activeTab, setActiveTab] = useState<"api-keys" | "sso" | "roles" | "audit" | "gdpr">("api-keys");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // API Keys state
  const [apiKeys, setApiKeys] = useState<api.ApiKey[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyExpiry, setNewKeyExpiry] = useState<number | null>(null);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [showKeyModal, setShowKeyModal] = useState(false);

  // SSO state
  const [ssoConfig, setSsoConfig] = useState<api.SSOConfig | null>(null);
  const [ssoProvider, setSsoProvider] = useState("oidc");
  const [ssoClientId, setSsoClientId] = useState("");
  const [ssoClientSecret, setSsoClientSecret] = useState("");
  const [ssoIssuerUrl, setSsoIssuerUrl] = useState("");
  const [ssoEntryPoint, setSsoEntryPoint] = useState("");
  const [ssoCert, setSsoCert] = useState("");
  const [ssoActive, setSsoActive] = useState(false);
  const [ssoMessage, setSsoMessage] = useState<string | null>(null);

  // Custom Roles state
  const [customRoles, setCustomRoles] = useState<api.CustomRole[]>([]);
  const [roleId, setRoleId] = useState("");
  const [roleName, setRoleName] = useState("");
  const [roleDesc, setRoleDesc] = useState("");
  const [rolePerms, setRolePerms] = useState<string[]>([]);
  const [roleMessage, setRoleMessage] = useState<string | null>(null);

  // Audit logs state
  const [auditLogs, setAuditLogs] = useState<api.AuditLog[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [filterAction, setFilterAction] = useState("");
  const [filterActor, setFilterActor] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [auditOffset, setAuditOffset] = useState(0);
  const auditLimit = 10;

  // GDPR state
  const [scrubUserId, setScrubUserId] = useState("");
  const [gdprMessage, setGdprMessage] = useState<string | null>(null);

  // Fetch Workspace Details
  useEffect(() => {
    async function loadWorkspace() {
      try {
        const ws = await wsApi.getWorkspace(workspaceId);
        setWorkspace(ws);
      } catch (err) {
        console.error("Failed to load workspace details", err);
      }
    }
    if (workspaceId) {
      loadWorkspace();
    }
  }, [workspaceId]);

  // Load API Keys
  const loadApiKeys = useCallback(async () => {
    try {
      const keys = await api.getKeys();
      setApiKeys(keys);
    } catch (err) {
      console.error(err);
    }
  }, []);

  // Load SSO Config
  const loadSSOConfig = useCallback(async () => {
    try {
      const config = await api.getSSOConfig();
      if (config) {
        setSsoConfig(config);
        setSsoProvider(config.provider_type);
        setSsoClientId(config.client_id);
        setSsoIssuerUrl(config.issuer_url || "");
        setSsoEntryPoint(config.entry_point || "");
        setSsoActive(config.is_active);
      }
    } catch (err) {
      console.error(err);
    }
  }, []);

  // Load Custom Roles
  const loadCustomRoles = useCallback(async () => {
    try {
      const roles = await api.getCustomRoles();
      setCustomRoles(roles);
    } catch (err) {
      console.error(err);
    }
  }, []);

  // Load Audit Logs
  const loadAuditLogs = useCallback(async () => {
    try {
      const res = await api.getAuditLogs({
        workspace_id: workspaceId,
        action: filterAction,
        actor_id: filterActor,
        status: filterStatus,
        limit: auditLimit,
        offset: auditOffset,
      });
      setAuditLogs(res.logs);
      setAuditTotal(res.total);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId, filterAction, filterActor, filterStatus, auditOffset]);

  // Initial load
  useEffect(() => {
    async function init() {
      setLoading(true);
      setError(null);
      try {
        await Promise.all([
          loadApiKeys(),
          loadSSOConfig(),
          loadCustomRoles(),
          loadAuditLogs(),
        ]);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load security console data.");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [loadApiKeys, loadSSOConfig, loadCustomRoles, loadAuditLogs]);

  // Create API Key handler
  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName) return;
    try {
      const res = await api.createKey(newKeyName, newKeyExpiry);
      if (res.key) {
        setCreatedKey(res.key);
        setShowKeyModal(true);
      }
      setNewKeyName("");
      setNewKeyExpiry(null);
      loadApiKeys();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to create API key");
    }
  };

  // Revoke API Key handler
  const handleRevokeKey = async (keyId: string) => {
    if (!confirm("Are you sure you want to revoke this API key? This cannot be undone.")) return;
    try {
      await api.revokeKey(keyId);
      loadApiKeys();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to revoke API key");
    }
  };

  // Save SSO Config handler
  const handleSaveSSO = async (e: React.FormEvent) => {
    e.preventDefault();
    setSsoMessage(null);
    try {
      const config = await api.saveSSOConfig({
        provider_type: ssoProvider,
        client_id: ssoClientId,
        client_secret: ssoClientSecret || undefined,
        issuer_url: ssoIssuerUrl || undefined,
        entry_point: ssoEntryPoint || undefined,
        x509_cert: ssoCert || undefined,
        is_active: ssoActive,
      });
      setSsoConfig(config);
      setSsoMessage("SSO Configuration saved successfully!");
    } catch (err) {
      setSsoMessage(err instanceof ApiError ? err.message : "Failed to save SSO config");
    }
  };

  // Create Custom Role handler
  const handleCreateRole = async (e: React.FormEvent) => {
    e.preventDefault();
    setRoleMessage(null);
    if (!roleId || !roleName || rolePerms.length === 0) {
      setRoleMessage("Role ID, Name, and at least one permission are required.");
      return;
    }
    try {
      await api.createCustomRole({
        id: roleId,
        name: roleName,
        description: roleDesc || null,
        permissions: rolePerms,
      });
      setRoleId("");
      setRoleName("");
      setRoleDesc("");
      setRolePerms([]);
      setRoleMessage("Custom Role created successfully!");
      loadCustomRoles();
    } catch (err) {
      setRoleMessage(err instanceof ApiError ? err.message : "Failed to create custom role");
    }
  };

  // Delete Custom Role handler
  const handleDeleteRole = async (id: string) => {
    if (!confirm("Are you sure you want to delete this custom role?")) return;
    try {
      await api.deleteCustomRole(id);
      loadCustomRoles();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to delete custom role");
    }
  };

  // GDPR scrub handler
  const handleScrubUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setGdprMessage(null);
    if (!scrubUserId) return;
    if (!confirm("CRITICAL WARNING: This will permanently purge and redact all personal information for this user. Continue?")) return;
    try {
      const res = await api.scrubUserData(scrubUserId);
      setGdprMessage(`GDPR Scrubbing initiated! Task ID: ${res.scrubbing_task_id}`);
      setScrubUserId("");
    } catch (err) {
      setGdprMessage(err instanceof ApiError ? err.message : "Failed to initiate GDPR scrub");
    }
  };

  const togglePermission = (perm: string) => {
    if (rolePerms.includes(perm)) {
      setRolePerms(rolePerms.filter((p) => p !== perm));
    } else {
      setRolePerms([...rolePerms, perm]);
    }
  };

  const availablePermissions = [
    "workspace.read",
    "workspace.write",
    "workspace.admin",
    "document.read",
    "document.write",
    "document.delete",
    "chat.read",
    "chat.write",
    "note.read",
    "note.write",
    "agent.read",
    "agent.write",
    "agent.execute",
    "security.admin",
    "compliance.admin",
  ];

  if (loading) {
    return (
      <div className="security-dashboard">
        <header className="security-header">
          <div className="security-title-area">
            <h1>🛡️ Security &amp; Governance Console</h1>
            <p className="security-subtitle">Loading security status &amp; configurations...</p>
          </div>
        </header>
        <div className="security-panel-content" style={{ textAlign: "center", padding: 40 }}>
          <span className="spin" style={{ fontSize: 24 }}>🧠</span> Loading security workspace...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="security-dashboard">
        <header className="security-header">
          <div className="security-title-area">
            <h1>🛡️ Security &amp; Governance Console</h1>
            <Link to={`/workspace/${workspaceId}`} style={{ color: "#38bdf8", textDecoration: "none" }}>← Back to Workspace</Link>
          </div>
        </header>
        <div className="security-panel-content">
          <div className="security-badge danger" style={{ padding: "8px 16px", fontSize: 14 }}>
            Error: {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="security-dashboard">
      <header className="security-header">
        <div className="security-title-area">
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <Link to={`/workspace/${workspaceId}`} className="security-btn secondary" style={{ padding: "6px 12px" }}>
              ←
            </Link>
            <h1>🛡️ Enterprise Security &amp; Governance</h1>
          </div>
          <p className="security-subtitle">
            Zero Trust IAM configuration, Custom Roles, SSO Identifiers, and Audit Logs for Workspace: <strong>{workspace?.name}</strong>
          </p>
        </div>
      </header>

      <div className="security-banner">
        <span>💡</span>
        <div>
          <strong>Zero Trust Active:</strong> All resource paths require explicit authentication, IP CIDR verification, and RBAC policies. Compliance actions are audited and immutable.
        </div>
      </div>

      {/* Tab Navigation */}
      <nav className="security-tabs-bar">
        <button
          className={`security-tab-btn ${activeTab === "api-keys" ? "active" : ""}`}
          onClick={() => setActiveTab("api-keys")}
        >
          🔑 API Keys
        </button>
        <button
          className={`security-tab-btn ${activeTab === "sso" ? "active" : ""}`}
          onClick={() => setActiveTab("sso")}
        >
          🌐 SSO Identity Provider
        </button>
        <button
          className={`security-tab-btn ${activeTab === "roles" ? "active" : ""}`}
          onClick={() => setActiveTab("roles")}
        >
          🎭 Custom Roles
        </button>
        <button
          className={`security-tab-btn ${activeTab === "audit" ? "active" : ""}`}
          onClick={() => setActiveTab("audit")}
        >
          📜 Compliance Audit Logs
        </button>
        <button
          className={`security-tab-btn ${activeTab === "gdpr" ? "active" : ""}`}
          onClick={() => setActiveTab("gdpr")}
        >
          🗑️ GDPR Sandbox
        </button>
      </nav>

      {/* API Keys Tab */}
      {activeTab === "api-keys" && (
        <div className="security-panel-content">
          <h2 className="security-section-title">Developer &amp; Service API Keys</h2>
          <p className="security-section-desc">
            Generate credentials to integrate LexiMind with external pipelines, workflow builders, or scripts. Service accounts can also be authenticated using these keys.
          </p>

          <form onSubmit={handleCreateKey} className="security-form" style={{ marginBottom: 32 }}>
            <div className="security-form-row">
              <label>API Key Name</label>
              <input
                type="text"
                className="security-input"
                placeholder="e.g. Jenkins Integration Client"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                required
              />
            </div>
            <div className="security-form-row">
              <label>Expiration (Optional)</label>
              <select
                className="security-select"
                value={newKeyExpiry || ""}
                onChange={(e) => setNewKeyExpiry(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Never Expires</option>
                <option value="86400">1 Day</option>
                <option value="604800">7 Days</option>
                <option value="2592000">30 Days</option>
              </select>
            </div>
            <button type="submit" className="security-btn">
              Generate API Key
            </button>
          </form>

          <h3 className="security-section-title">Active Credentials</h3>
          <div className="security-table-container">
            <table className="security-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Prefix</th>
                  <th>Created At</th>
                  <th>Expires At</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {apiKeys.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", color: "#64748b" }}>
                      No active API keys found.
                    </td>
                  </tr>
                ) : (
                  apiKeys.map((key) => (
                    <tr key={key.id}>
                      <td><strong>{key.name}</strong></td>
                      <td><code>{key.prefix}***</code></td>
                      <td>{new Date(key.created_at).toLocaleString()}</td>
                      <td>{key.expires_at ? new Date(key.expires_at).toLocaleString() : "Never"}</td>
                      <td>
                        <span className={`security-badge ${key.is_active ? "success" : "warning"}`}>
                          {key.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td>
                        <button onClick={() => handleRevokeKey(key.id)} className="security-btn danger small" style={{ padding: "4px 8px", fontSize: 12 }}>
                          Revoke
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* SSO Tab */}
      {activeTab === "sso" && (
        <div className="security-panel-content">
          <h2 className="security-section-title">SSO &amp; Federated Identity Configuration</h2>
          <p className="security-section-desc">
            Enable Single Sign-On (SSO) to enforce enterprise access controls, sync custom active directories (Okta, Keycloak, Entra, Workspace), and enable JIT user provisioning.
          </p>

          {ssoMessage && (
            <div className="security-banner" style={{ borderLeft: "4px solid #4f46e5" }}>
              {ssoMessage}
            </div>
          )}

          <form onSubmit={handleSaveSSO} className="security-form">
            <div className="security-form-row">
              <label>Provider Type</label>
              <select
                className="security-select"
                value={ssoProvider}
                onChange={(e) => setSsoProvider(e.target.value)}
              >
                <option value="oidc">OpenID Connect (OIDC)</option>
                <option value="saml">SAML 2.0 Identity Provider</option>
                <option value="okta">Okta Enterprise</option>
                <option value="entra">Microsoft Entra ID</option>
                <option value="google">Google Workspace Enterprise</option>
                <option value="keycloak">Keycloak Federated SSO</option>
              </select>
            </div>

            <div className="security-form-row">
              <label>Client ID (Metadata Endpoint Entity ID)</label>
              <input
                type="text"
                className="security-input"
                placeholder="e.g. 0oa8a1b2c3d4e5f6g7h8"
                value={ssoClientId}
                onChange={(e) => setSsoClientId(e.target.value)}
                required
              />
            </div>

            <div className="security-form-row">
              <label>Client Secret (Optional, for OIDC flow)</label>
              <input
                type="password"
                className="security-input"
                placeholder="••••••••••••••••"
                value={ssoClientSecret}
                onChange={(e) => setSsoClientSecret(e.target.value)}
              />
            </div>

            <div className="security-form-row">
              <label>Issuer URL (or SAML Metadata URL)</label>
              <input
                type="url"
                className="security-input"
                placeholder="https://identity.yourcompany.com/oauth2/default"
                value={ssoIssuerUrl}
                onChange={(e) => setSsoIssuerUrl(e.target.value)}
              />
            </div>

            <div className="security-form-row">
              <label>SAML Sign-On Entry Point (SSO Landing Page)</label>
              <input
                type="url"
                className="security-input"
                placeholder="https://identity.yourcompany.com/saml2/sso"
                value={ssoEntryPoint}
                onChange={(e) => setSsoEntryPoint(e.target.value)}
              />
            </div>

            <div className="security-form-row">
              <label>X.509 Certificate (SAML Signature verification PEM)</label>
              <textarea
                className="security-textarea"
                rows={5}
                placeholder="-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
                value={ssoCert}
                onChange={(e) => setSsoCert(e.target.value)}
              />
            </div>

            <div className="security-form-row" style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
              <input
                type="checkbox"
                id="sso-toggle"
                checked={ssoActive}
                onChange={(e) => setSsoActive(e.target.checked)}
              />
              <label htmlFor="sso-toggle">Enforce SSO login redirect for all corporate email accounts</label>
            </div>

            <button type="submit" className="security-btn">
              Save SSO Configuration
            </button>
          </form>

          {ssoConfig && (
            <div style={{ marginTop: 24, padding: 16, background: "#1e293b", borderRadius: 8, border: "1px solid #334155" }}>
              <div style={{ fontSize: 13, color: "#94a3b8", marginBottom: 6 }}>Active SSO Settings:</div>
              <div style={{ fontSize: 14 }}>Provider: <strong style={{ color: "#38bdf8" }}>{ssoConfig.provider_type.toUpperCase()}</strong></div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>Client ID: {ssoConfig.client_id}</div>
              <div style={{ fontSize: 12, color: "#64748b" }}>Status: <span style={{ color: ssoConfig.is_active ? "#10b981" : "#f59e0b" }}>{ssoConfig.is_active ? "Enforced" : "Inactive"}</span></div>
            </div>
          )}
        </div>
      )}

      {/* Custom Roles Tab */}
      {activeTab === "roles" && (
        <div className="security-panel-content">
          <h2 className="security-section-title">Enterprise Custom RBAC Roles</h2>
          <p className="security-section-desc">
            Define tailored roles that grant exact permissions to teams, users, or API credentials. These roles can be scoped globally or to a specific organization member.
          </p>

          {roleMessage && (
            <div className="security-banner">
              {roleMessage}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 32 }}>
            {/* Create Role Form */}
            <form onSubmit={handleCreateRole} className="security-form">
              <h3 className="security-section-title" style={{ fontSize: 16 }}>Create Custom Role</h3>
              <div className="security-form-row">
                <label>Role ID (Internal Slug)</label>
                <input
                  type="text"
                  className="security-input"
                  placeholder="e.g. security-audit-team"
                  value={roleId}
                  onChange={(e) => setRoleId(e.target.value)}
                  required
                />
              </div>

              <div className="security-form-row">
                <label>Role Title</label>
                <input
                  type="text"
                  className="security-input"
                  placeholder="e.g. Security Audit Team"
                  value={roleName}
                  onChange={(e) => setRoleName(e.target.value)}
                  required
                />
              </div>

              <div className="security-form-row">
                <label>Description</label>
                <input
                  type="text"
                  className="security-input"
                  placeholder="Explain the scope of this role..."
                  value={roleDesc}
                  onChange={(e) => setRoleDesc(e.target.value)}
                />
              </div>

              <div className="security-form-row">
                <label>Select Permissions</label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, background: "#0f172a", padding: 12, borderRadius: 8, border: "1px solid #334155", maxHeight: 180, overflowY: "auto" }}>
                  {availablePermissions.map((perm) => (
                    <div key={perm} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input
                        type="checkbox"
                        id={`perm-${perm}`}
                        checked={rolePerms.includes(perm)}
                        onChange={() => togglePermission(perm)}
                      />
                      <label htmlFor={`perm-${perm}`} style={{ fontSize: 12, wordBreak: "break-all" }}>{perm}</label>
                    </div>
                  ))}
                </div>
              </div>

              <button type="submit" className="security-btn" style={{ marginTop: 12 }}>
                Save Custom Role
              </button>
            </form>

            {/* List Custom Roles */}
            <div>
              <h3 className="security-section-title" style={{ fontSize: 16 }}>Active Roles</h3>
              <div className="security-grid" style={{ gridTemplateColumns: "1fr" }}>
                {customRoles.length === 0 ? (
                  <div style={{ textAlign: "center", color: "#64748b", padding: 20 }}>
                    No custom roles defined. Standard system roles (Owner, Admin, Editor, Viewer) are active.
                  </div>
                ) : (
                  customRoles.map((role) => (
                    <div className="security-card" key={role.id} style={{ minHeight: "auto" }}>
                      <div className="security-card-header">
                        <h4 className="security-card-title">{role.name}</h4>
                        <span className="security-badge info">{role.id}</span>
                      </div>
                      <p className="security-card-body">{role.description || "No description provided."}</p>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 12 }}>
                        {role.permissions.map((p) => (
                          <span key={p} style={{ background: "#0f172a", color: "#cbd5e1", fontSize: 10, padding: "2px 6px", borderRadius: 4, border: "1px solid #334155" }}>
                            {p}
                          </span>
                        ))}
                      </div>
                      <button onClick={() => handleDeleteRole(role.id)} className="security-btn danger small" style={{ alignSelf: "flex-end" }}>
                        Delete Role
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Compliance Audit Logs Tab */}
      {activeTab === "audit" && (
        <div className="security-panel-content">
          <h2 className="security-section-title">Compliance Audit Telemetry</h2>
          <p className="security-section-desc">
            Search and trace actions performed on this workspace. Every compliance evaluation, secret request, IAM assignment, and data change triggers an immutable audit log.
          </p>

          {/* Filters */}
          <div className="security-filter-row">
            <input
              type="text"
              className="security-input"
              placeholder="Filter by action..."
              value={filterAction}
              onChange={(e) => { setFilterAction(e.target.value); setAuditOffset(0); }}
            />
            <input
              type="text"
              className="security-input"
              placeholder="Filter by actor ID..."
              value={filterActor}
              onChange={(e) => { setFilterActor(e.target.value); setAuditOffset(0); }}
            />
            <select
              className="security-select"
              value={filterStatus}
              onChange={(e) => { setFilterStatus(e.target.value); setAuditOffset(0); }}
            >
              <option value="">All Statuses</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
            </select>
            <button className="security-btn" onClick={loadAuditLogs}>
              🔍 Refresh
            </button>
          </div>

          {/* Audit Logs Table */}
          <div className="security-table-container">
            <table className="security-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Action</th>
                  <th>Actor</th>
                  <th>Resource</th>
                  <th>IP Address</th>
                  <th>Status</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: "center", color: "#64748b" }}>
                      No audit events matching these criteria.
                    </td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr key={log.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{new Date(log.timestamp).toLocaleString()}</td>
                      <td><strong>{log.action}</strong></td>
                      <td>
                        <div style={{ fontSize: 12 }}>
                          <code>{log.actor_id}</code>
                          {log.actor_email && <div style={{ color: "#64748b" }}>{log.actor_email}</div>}
                        </div>
                      </td>
                      <td>
                        <span style={{ fontSize: 12, color: "#94a3b8" }}>{log.resource_type}:</span>{" "}
                        <code>{log.resource_id}</code>
                      </td>
                      <td><code>{log.ip_address || "Internal"}</code></td>
                      <td>
                        <span className={`security-badge ${log.status === "success" ? "success" : "danger"}`}>
                          {log.status}
                        </span>
                      </td>
                      <td>
                        {log.failure_reason && (
                          <div style={{ fontSize: 11, color: "#ef4444", maxWidth: 200, wordBreak: "break-word" }}>
                            Reason: {log.failure_reason}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16 }}>
            <span style={{ fontSize: 13, color: "#94a3b8" }}>
              Showing {auditLogs.length} of {auditTotal} logs
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="security-btn secondary small"
                disabled={auditOffset === 0}
                onClick={() => setAuditOffset(Math.max(0, auditOffset - auditLimit))}
              >
                Previous Page
              </button>
              <button
                className="security-btn secondary small"
                disabled={auditOffset + auditLimit >= auditTotal}
                onClick={() => setAuditOffset(auditOffset + auditLimit)}
              >
                Next Page
              </button>
            </div>
          </div>
        </div>
      )}

      {/* GDPR & Sandbox Tab */}
      {activeTab === "gdpr" && (
        <div className="security-panel-content">
          <h2 className="security-section-title">GDPR Data Portability &amp; Redaction Sandbox</h2>
          <p className="security-section-desc">
            Enforce compliance policies for data residency and privacy. Easily execute right-to-be-forgotten scrubbing tasks that purge all conversational logs, semantic memory fragments, and cached prompt outputs for target users.
          </p>

          {gdprMessage && (
            <div className="security-banner">
              {gdprMessage}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 32 }}>
            {/* Purge Form */}
            <form onSubmit={handleScrubUser} className="security-form">
              <h3 className="security-section-title" style={{ fontSize: 16 }}>Right to be Forgotten (GDPR Article 17)</h3>
              <div className="security-form-row">
                <label>User ID (or email account to scrub)</label>
                <input
                  type="text"
                  className="security-input"
                  placeholder="e.g. user_f12345678"
                  value={scrubUserId}
                  onChange={(e) => setScrubUserId(e.target.value)}
                  required
                />
              </div>
              <button type="submit" className="security-btn danger">
                ❌ Initiate Permanent User Scrub
              </button>
            </form>

            {/* Zero Trust Policy Simulator */}
            <div className="security-card" style={{ minHeight: "auto", background: "#0f172a", borderColor: "#334155" }}>
              <h3 className="security-section-title" style={{ fontSize: 16 }}>Compliance Policy Inspector</h3>
              <p style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.5, margin: "0 0 16px 0" }}>
                Simulate how the Zero Trust engine evaluates security policies under different conditions. Check if requests are blocked due to unauthorized IP ranges or access hours.
              </p>
              <div style={{ display: "flex", alignSelf: "stretch", flexDirection: "column", gap: 8, background: "#1e293b", padding: 16, borderRadius: 8, border: "1px solid #334155" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                  <span style={{ color: "#94a3b8" }}>Current Client IP:</span>
                  <span style={{ fontFamily: "monospace", color: "#38bdf8" }}>127.0.0.1 (Authorized Localhost)</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                  <span style={{ color: "#94a3b8" }}>Temporal Window:</span>
                  <span style={{ color: "#10b981" }}>Open (Always Allowed)</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                  <span style={{ color: "#94a3b8" }}>Data scrubbing rate-limiter:</span>
                  <span style={{ color: "#10b981" }}>0 / 10 calls active</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* API Key Modal Display */}
      {showKeyModal && createdKey && (
        <div className="security-modal-overlay">
          <div className="security-modal">
            <h3 className="security-modal-header">🔑 API Key Generated Successfully</h3>
            <p className="security-modal-body">
              Please copy the API key below. For security purposes, <strong>this key will only be shown once</strong>. You will not be able to retrieve it again.
            </p>
            <div className="security-key-display">
              <span>{createdKey}</span>
              <button
                className="security-btn secondary small"
                style={{ padding: "4px 8px", fontSize: 12 }}
                onClick={() => {
                  navigator.clipboard.writeText(createdKey);
                  alert("API key copied to clipboard!");
                }}
              >
                📋 Copy
              </button>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                className="security-btn"
                onClick={() => {
                  setShowKeyModal(false);
                  setCreatedKey(null);
                }}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
