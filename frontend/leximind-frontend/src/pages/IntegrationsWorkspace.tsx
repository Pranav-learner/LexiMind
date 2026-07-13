import { useEffect, useState, useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/integrations";
import * as wsApi from "../api/workspaces";
import { ApiError } from "../api/client";
import type { Workspace } from "../types";

export default function IntegrationsWorkspace() {
  const { workspaceId = "" } = useParams();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [activeTab, setActiveTab] = useState<"marketplace" | "installed" | "automation" | "webhooks" | "scheduler" | "mcp" | "events">("marketplace");
  const [loading, setLoading] = useState(true);

  // Data states
  const [connectorTypes, setConnectorTypes] = useState<api.ConnectorType[]>([]);
  const [connectorInstances, setConnectorInstances] = useState<api.ConnectorInstance[]>([]);
  const [webhooks, setWebhooks] = useState<api.WebhookEndpoint[]>([]);
  const [workflows, setWorkflows] = useState<api.AutomationWorkflow[]>([]);
  const [scheduledJobs, setScheduledJobs] = useState<api.ScheduledJob[]>([]);
  const [mcpServers, setMcpServers] = useState<api.MCPServerRegistration[]>([]);
  const [integrationEvents, setIntegrationEvents] = useState<api.IntegrationEvent[]>([]);

  // Active configurations/modals
  const [installingConnector, setInstallingConnector] = useState<api.ConnectorType | null>(null);
  const [configuringAuth, setConfiguringAuth] = useState<api.ConnectorInstance | null>(null);
  const [browsingInstance, setBrowsingInstance] = useState<api.ConnectorInstance | null>(null);
  const [browsedPath, setBrowsedPath] = useState("/");
  const [browsedItems, setBrowsedItems] = useState<any[]>([]);
  const [browsedLoading, setBrowsedLoading] = useState(false);

  // Form states
  const [connDisplayName, setConnDisplayName] = useState("");
  const [connConfigJson, setConnConfigJson] = useState("{}");
  const [authType, setAuthType] = useState("oauth2");
  const [authCredsJson, setAuthCredsJson] = useState("{}");
  const [authScopes, setAuthScopes] = useState<string[]>([]);
  const [newWebhook, setNewWebhook] = useState({ name: "", direction: "incoming", url: "", eventFilterCsv: "github.push,github.pull_request" });
  const [newWorkflow, setNewWorkflow] = useState({ name: "", description: "", triggerType: "event", triggerPattern: "connector.sync.completed", field: "payload.status", operator: "equals", value: "success", actionType: "notification", actionMsg: "Sync completed successfully." });
  const [newJob, setNewJob] = useState({ name: "", jobType: "connector_sync", schedule: "0 0 * * *", configJson: "{}" });
  const [newMcp, setNewMcp] = useState({ name: "", serverUrl: "", transport: "sse", authConfigJson: "{}" });

  // Notifications
  const [alertMsg, setAlertMsg] = useState<string | null>(null);
  const [alertType, setAlertType] = useState<"success" | "danger">("success");

  const notify = (msg: string, type: "success" | "danger" = "success") => {
    setAlertMsg(msg);
    setAlertType(type);
    setTimeout(() => setAlertMsg(null), 5000);
  };

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
    if (workspaceId) loadWorkspace();
  }, [workspaceId]);

  // Load Marketplace & Instances
  const loadMarketplace = useCallback(async () => {
    try {
      const types = await api.listConnectorTypes(workspaceId);
      setConnectorTypes(types);
      const instances = await api.listConnectorInstances(workspaceId);
      setConnectorInstances(instances);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId]);

  // Load Webhooks
  const loadWebhooks = useCallback(async () => {
    try {
      const res = await api.listWebhooks(workspaceId);
      setWebhooks(res);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId]);

  // Load Workflows
  const loadWorkflows = useCallback(async () => {
    try {
      const res = await api.listWorkflows(workspaceId);
      setWorkflows(res);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId]);

  // Load Scheduled Jobs
  const loadScheduledJobs = useCallback(async () => {
    try {
      const res = await api.listScheduledJobs(workspaceId);
      setScheduledJobs(res);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId]);

  // Load MCP Servers
  const loadMCPServers = useCallback(async () => {
    try {
      const res = await api.listMCPServers(workspaceId);
      setMcpServers(res);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId]);

  // Load Real-time events
  const loadEvents = useCallback(async () => {
    try {
      const res = await api.listIntegrationEvents(workspaceId);
      setIntegrationEvents(res);
    } catch (err) {
      console.error(err);
    }
  }, [workspaceId]);

  // Load active tab data
  useEffect(() => {
    if (!workspaceId) return;
    setLoading(true);
    const promises = [];
    if (activeTab === "marketplace" || activeTab === "installed") {
      promises.push(loadMarketplace());
    } else if (activeTab === "webhooks") {
      promises.push(loadWebhooks());
    } else if (activeTab === "automation") {
      promises.push(loadWorkflows());
      promises.push(loadMarketplace());
    } else if (activeTab === "scheduler") {
      promises.push(loadScheduledJobs());
    } else if (activeTab === "mcp") {
      promises.push(loadMCPServers());
    } else if (activeTab === "events") {
      promises.push(loadEvents());
    }
    Promise.all(promises).finally(() => setLoading(false));
  }, [activeTab, workspaceId, loadMarketplace, loadWebhooks, loadWorkflows, loadScheduledJobs, loadMCPServers, loadEvents]);

  // Installs a new connector instance
  const handleInstall = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!installingConnector) return;
    try {
      let config = {};
      try {
        config = JSON.parse(connConfigJson);
      } catch (err) {
        notify("Invalid JSON config format", "danger");
        return;
      }
      await api.installConnector(workspaceId, {
        connector_type: installingConnector.type,
        display_name: connDisplayName || installingConnector.name,
        config,
      });
      notify(`Connector '${installingConnector.name}' installed successfully!`);
      setInstallingConnector(null);
      loadMarketplace();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to install connector.", "danger");
    }
  };

  // Delete connector instance
  const handleDeleteConnector = async (id: string) => {
    if (!window.confirm("Are you sure you want to uninstall this connector? This removes credentials.")) return;
    try {
      await api.deleteConnector(workspaceId, id);
      notify("Connector uninstalled.");
      loadMarketplace();
    } catch (err) {
      notify("Failed to uninstall connector.", "danger");
    }
  };

  // Configure Credentials
  const handleConfigureAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!configuringAuth) return;
    try {
      let credentials = {};
      try {
        credentials = JSON.parse(authCredsJson);
      } catch (err) {
        notify("Invalid credentials JSON format", "danger");
        return;
      }
      const res = await api.configureConnectorAuth(workspaceId, configuringAuth.id, {
        auth_type: authType,
        credentials,
        scopes: authScopes,
      });
      if (res.is_valid) {
        notify("Credentials saved and verified!");
        setConfiguringAuth(null);
        loadMarketplace();
      } else {
        notify(`Verification failed: ${res.message}`, "danger");
      }
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to save auth settings.", "danger");
    }
  };

  // Sync connector instance
  const handleSyncConnector = async (id: string) => {
    try {
      notify("Starting synchronization job...");
      const res = await api.syncConnector(workspaceId, id, { resource_types: ["files", "documents", "messages"] });
      if (res.status === "completed") {
        notify(`Sync finished! Synced ${res.items_synced} items.`);
      } else {
        notify(`Sync failed: ${res.error}`, "danger");
      }
      loadMarketplace();
    } catch (err) {
      notify("Failed to execute sync.", "danger");
    }
  };

  // Browse connector path
  const handleBrowseConnector = async (id: string, path: string) => {
    setBrowsedLoading(true);
    setBrowsedPath(path);
    try {
      const res = await api.browseConnector(workspaceId, id, { path });
      setBrowsedItems(res.items);
    } catch (err) {
      notify("Could not browse path.", "danger");
    } finally {
      setBrowsedLoading(false);
    }
  };

  // Webhooks CRUD
  const handleCreateWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const filter = newWebhook.eventFilterCsv.split(",").map(s => s.trim()).filter(Boolean);
      await api.createWebhook(workspaceId, {
        name: newWebhook.name,
        direction: newWebhook.direction,
        url: newWebhook.url || undefined,
        event_filter: filter,
      });
      notify("Webhook endpoint registered successfully!");
      setNewWebhook({ name: "", direction: "incoming", url: "", eventFilterCsv: "github.push,github.pull_request" });
      loadWebhooks();
    } catch (err) {
      notify("Failed to register webhook.", "danger");
    }
  };

  const handleDeleteWebhook = async (id: string) => {
    if (!window.confirm("Are you sure?")) return;
    try {
      await api.deleteWebhook(workspaceId, id);
      notify("Webhook endpoint deleted.");
      loadWebhooks();
    } catch (err) {
      notify("Failed to delete webhook.", "danger");
    }
  };

  // Workflows CRUD & manually trigger
  const handleCreateWorkflow = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const connectorActions = connectorInstances.filter(c => c.category === "communication");
      const connectorId = connectorActions.length > 0 ? connectorActions[0].id : "conn_default";

      await api.createWorkflow(workspaceId, {
        name: newWorkflow.name,
        description: newWorkflow.description,
        trigger: { type: newWorkflow.triggerType, pattern: newWorkflow.triggerPattern },
        conditions: [{ field: newWorkflow.field, operator: newWorkflow.operator, value: newWorkflow.value }],
        actions: [
          {
            type: newWorkflow.actionType,
            config: {
              connector_id: connectorId,
              message: newWorkflow.actionMsg,
            },
          },
        ],
      });
      notify("Automation workflow created!");
      setNewWorkflow({ name: "", description: "", triggerType: "event", triggerPattern: "connector.sync.completed", field: "payload.status", operator: "equals", value: "success", actionType: "notification", actionMsg: "Sync completed successfully." });
      loadWorkflows();
    } catch (err) {
      notify("Failed to create workflow.", "danger");
    }
  };

  const handleRunWorkflow = async (id: string) => {
    try {
      notify("Triggering workflow execution manually...");
      const res = await api.runWorkflow(workspaceId, id);
      if (res.status === "completed") {
        notify(`Workflow completed successfully in ${res.duration_ms.toFixed(1)}ms!`);
      } else {
        notify(`Workflow failed: ${res.error}`, "danger");
      }
      loadWorkflows();
    } catch (err) {
      notify("Failed to execute workflow.", "danger");
    }
  };

  const handleDeleteWorkflow = async (id: string) => {
    if (!window.confirm("Delete this workflow?")) return;
    try {
      await api.deleteWorkflow(workspaceId, id);
      notify("Workflow deleted.");
      loadWorkflows();
    } catch (err) {
      notify("Failed to delete workflow.", "danger");
    }
  };

  // Scheduler CRUD
  const handleCreateJob = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      let config = {};
      try {
        config = JSON.parse(newJob.configJson);
      } catch (err) {
        notify("Invalid JSON config payload", "danger");
        return;
      }
      await api.createScheduledJob(workspaceId, {
        name: newJob.name,
        job_type: newJob.jobType,
        schedule: newJob.schedule,
        config,
      });
      notify("Scheduled job registered!");
      setNewJob({ name: "", jobType: "connector_sync", schedule: "0 0 * * *", configJson: "{}" });
      loadScheduledJobs();
    } catch (err) {
      notify("Failed to register job.", "danger");
    }
  };

  const handleDeleteJob = async (id: string) => {
    if (!window.confirm("Are you sure?")) return;
    try {
      await api.deleteScheduledJob(workspaceId, id);
      notify("Job deleted.");
      loadScheduledJobs();
    } catch (err) {
      notify("Failed to delete job.", "danger");
    }
  };

  // MCP Servers CRUD
  const handleRegisterMcp = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      let authConfig = {};
      try {
        authConfig = JSON.parse(newMcp.authConfigJson);
      } catch (err) {
        notify("Invalid JSON for Auth Config", "danger");
        return;
      }
      await api.registerMCPServer(workspaceId, {
        name: newMcp.name,
        server_url: newMcp.serverUrl,
        transport: newMcp.transport,
        auth_config: authConfig,
      });
      notify("MCP Server registered successfully!");
      setNewMcp({ name: "", serverUrl: "", transport: "sse", authConfigJson: "{}" });
      loadMCPServers();
    } catch (err) {
      notify("Failed to register MCP server.", "danger");
    }
  };

  const handleDeleteMcp = async (id: string) => {
    if (!window.confirm("Remove this MCP Server?")) return;
    try {
      await api.deleteMCPServer(workspaceId, id);
      notify("MCP Server unregistered.");
      loadMCPServers();
    } catch (err) {
      notify("Failed to delete MCP server.", "danger");
    }
  };

  return (
    <div className="integrations-dashboard">
      <header className="integrations-header">
        <div className="integrations-title-area">
          <Link className="ws-back" to={`/workspace/${workspaceId}`}>
            ← Workspace Details
          </Link>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
            <h1>🔌 Integrations &amp; Automation</h1>
            {workspace && (
              <span className="integrations-badge info" style={{ textTransform: "none" }}>
                {workspace.name}
              </span>
            )}
          </div>
          <p className="integrations-subtitle">
            Configure connectors, incoming webhooks, automation engines, backgrounds timers, and external MCP servers.
          </p>
        </div>
      </header>

      {alertMsg && (
        <div className={`integrations-banner ${alertType === "danger" ? "danger" : "success"}`} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{alertType === "danger" ? "⚠️" : "✅"} {alertMsg}</span>
          <button style={{ background: "transparent", border: "none", color: "inherit", cursor: "pointer", fontSize: 16 }} onClick={() => setAlertMsg(null)}>✕</button>
        </div>
      )}

      {/* Tabs */}
      <nav className="integrations-tabs-bar">
        <button className={`integrations-tab-btn ${activeTab === "marketplace" ? "active" : ""}`} onClick={() => setActiveTab("marketplace")}>
          🛍️ Marketplace
        </button>
        <button className={`integrations-tab-btn ${activeTab === "installed" ? "active" : ""}`} onClick={() => setActiveTab("installed")}>
          🔌 Installed Connectors
        </button>
        <button className={`integrations-tab-btn ${activeTab === "automation" ? "active" : ""}`} onClick={() => setActiveTab("automation")}>
          ⚡ Automation Workflows
        </button>
        <button className={`integrations-tab-btn ${activeTab === "webhooks" ? "active" : ""}`} onClick={() => setActiveTab("webhooks")}>
          🔗 Webhooks
        </button>
        <button className={`integrations-tab-btn ${activeTab === "scheduler" ? "active" : ""}`} onClick={() => setActiveTab("scheduler")}>
          📅 Scheduler Jobs
        </button>
        <button className={`integrations-tab-btn ${activeTab === "mcp" ? "active" : ""}`} onClick={() => setActiveTab("mcp")}>
          🌐 MCP Servers
        </button>
        <button className={`integrations-tab-btn ${activeTab === "events" ? "active" : ""}`} onClick={() => setActiveTab("events")}>
          📊 Events Log
        </button>
      </nav>

      {loading ? (
        <div className="integrations-panel-content">Loading...</div>
      ) : (
        <main className="integrations-tab-content">
          {/* Marketplace */}
          {activeTab === "marketplace" && (
            <div className="integrations-panel-content">
              <h2 className="integrations-section-title">Connector Marketplace</h2>
              <p className="integrations-section-desc">
                LexiMind provides 22 built-in enterprise connectors across storage, productivity, developer, and communication tools.
              </p>
              <div className="integrations-grid">
                {connectorTypes.map(c => {
                  const isInstalled = connectorInstances.some(inst => inst.connector_type === c.type);
                  return (
                    <div className="integrations-card" key={c.type}>
                      <div className="integrations-card-header">
                        <span className="integrations-card-icon">{c.icon || "🔌"}</span>
                        <span className="integrations-badge info">{c.category}</span>
                      </div>
                      <h3 className="integrations-card-title">{c.name}</h3>
                      <p className="integrations-card-body">{c.description || "Connect and synchronize data instantly."}</p>
                      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11, color: "#94a3b8", marginBottom: 12 }}>
                        <span>Auth: {c.auth_type}</span>
                        <span>Ver: {c.version}</span>
                      </div>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                        {c.capabilities.map(cap => (
                          <span key={cap} className="integrations-badge success" style={{ fontSize: 9 }}>
                            {cap.replace("can_", "")}
                          </span>
                        ))}
                      </div>
                      {isInstalled ? (
                        <button className="integrations-btn secondary" disabled>✓ Installed</button>
                      ) : (
                        <button className="integrations-btn" onClick={() => {
                          setInstallingConnector(c);
                          setConnDisplayName(c.name);
                          setConnConfigJson("{}");
                        }}>Install Connector</button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Installed Connectors */}
          {activeTab === "installed" && (
            <div className="integrations-panel-content">
              <h2 className="integrations-section-title">Installed Connectors</h2>
              <p className="integrations-section-desc">Manage installed instances, configure credentials, browse files, and trigger syncs.</p>
              {connectorInstances.length === 0 ? (
                <div style={{ padding: "40px 0", textAlign: "center", color: "#94a3b8" }}>No connectors installed yet. Visit the Marketplace to install one.</div>
              ) : (
                <div className="integrations-table-container">
                  <table className="integrations-table">
                    <thead>
                      <tr>
                        <th>Display Name</th>
                        <th>Type</th>
                        <th>Category</th>
                        <th>Health</th>
                        <th>Last Sync</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {connectorInstances.map(inst => (
                        <tr key={inst.id}>
                          <td>
                            <strong>{inst.display_name}</strong>
                          </td>
                          <td>{inst.connector_type}</td>
                          <td>{inst.category}</td>
                          <td>
                            <span className={`integrations-badge ${inst.health === "healthy" ? "success" : inst.health === "unknown" ? "warning" : "danger"}`}>
                              {inst.health}
                            </span>
                          </td>
                          <td>{inst.last_sync_at ? new Date(inst.last_sync_at).toLocaleString() : "Never"}</td>
                          <td>
                            <div style={{ display: "flex", gap: 8 }}>
                              <button className="integrations-btn small" onClick={() => {
                                setConfiguringAuth(inst);
                                setAuthType("oauth2");
                                setAuthCredsJson('{"access_token": "ya29.fake", "refresh_token": "rfr_123"}');
                              }}>🔑 Credentials</button>
                              <button className="integrations-btn small secondary" onClick={() => {
                                setBrowsingInstance(inst);
                                handleBrowseConnector(inst.id, "/");
                              }}>📂 Browse</button>
                              <button className="integrations-btn small" style={{ background: "#3b82f6" }} onClick={() => handleSyncConnector(inst.id)}>🔁 Sync</button>
                              <button className="integrations-btn small danger" onClick={() => handleDeleteConnector(inst.id)}>Uninstall</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Automation Workflows */}
          {activeTab === "automation" && (
            <div className="integrations-panel-content" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
              <div>
                <h2 className="integrations-section-title">Create Workflow</h2>
                <form className="integrations-form" onSubmit={handleCreateWorkflow}>
                  <div className="integrations-form-row">
                    <label>Workflow Name</label>
                    <input className="integrations-input" type="text" placeholder="e.g. Sync Completion Alert" value={newWorkflow.name} onChange={e => setNewWorkflow({ ...newWorkflow, name: e.target.value })} required />
                  </div>
                  <div className="integrations-form-row">
                    <label>Description</label>
                    <textarea className="integrations-textarea" placeholder="Describe the automation context..." value={newWorkflow.description} onChange={e => setNewWorkflow({ ...newWorkflow, description: e.target.value })} />
                  </div>
                  <div className="integrations-form-row">
                    <label>Trigger event type</label>
                    <input className="integrations-input" type="text" placeholder="e.g. connector.sync.completed" value={newWorkflow.triggerPattern} onChange={e => setNewWorkflow({ ...newWorkflow, triggerPattern: e.target.value })} required />
                  </div>
                  <div style={{ display: "flex", gap: 12 }}>
                    <div className="integrations-form-row" style={{ flex: 1 }}>
                      <label>Condition Field</label>
                      <input className="integrations-input" type="text" value={newWorkflow.field} onChange={e => setNewWorkflow({ ...newWorkflow, field: e.target.value })} />
                    </div>
                    <div className="integrations-form-row" style={{ flex: 1 }}>
                      <label>Operator</label>
                      <select className="integrations-select" value={newWorkflow.operator} onChange={e => setNewWorkflow({ ...newWorkflow, operator: e.target.value })}>
                        <option value="equals">equals</option>
                        <option value="contains">contains</option>
                        <option value="exists">exists</option>
                        <option value="not_exists">not_exists</option>
                      </select>
                    </div>
                    <div className="integrations-form-row" style={{ flex: 1 }}>
                      <label>Value</label>
                      <input className="integrations-input" type="text" value={newWorkflow.value} onChange={e => setNewWorkflow({ ...newWorkflow, value: e.target.value })} />
                    </div>
                  </div>
                  <div className="integrations-form-row">
                    <label>Action node type</label>
                    <select className="integrations-select" value={newWorkflow.actionType} onChange={e => setNewWorkflow({ ...newWorkflow, actionType: e.target.value })}>
                      <option value="notification">Direct notification (Slack/Teams)</option>
                      <option value="agent_task">Delegate agent task</option>
                    </select>
                  </div>
                  <div className="integrations-form-row">
                    <label>Action message/prompt</label>
                    <textarea className="integrations-textarea" value={newWorkflow.actionMsg} onChange={e => setNewWorkflow({ ...newWorkflow, actionMsg: e.target.value })} />
                  </div>
                  <button className="integrations-btn" type="submit">Create Workflow</button>
                </form>
              </div>

              <div>
                <h2 className="integrations-section-title">Active Workflows</h2>
                {workflows.length === 0 ? (
                  <div style={{ padding: "40px 0", textAlign: "center", color: "#94a3b8" }}>No active workflows. Create one on the left.</div>
                ) : (
                  <div className="integrations-grid" style={{ gridTemplateColumns: "1fr", margin: 0 }}>
                    {workflows.map(wf => (
                      <div className="integrations-card" key={wf.id} style={{ gap: 12 }}>
                        <div>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <h4 style={{ margin: 0, fontSize: 16 }}>{wf.name}</h4>
                            <span className={`integrations-badge ${wf.is_active ? "success" : "danger"}`}>{wf.is_active ? "active" : "paused"}</span>
                          </div>
                          <p style={{ fontSize: 12, color: "#94a3b8", margin: "4px 0 0 0" }}>{wf.description}</p>
                        </div>
                        <div style={{ fontSize: 12, background: "#0f172a", padding: 8, borderRadius: 6 }}>
                          <div>Trigger: <code>{wf.trigger.pattern || "*"}</code></div>
                          <div>Runs: {wf.execution_count}</div>
                          {wf.last_executed_at && <div>Last Executed: {new Date(wf.last_executed_at).toLocaleString()}</div>}
                        </div>
                        <div style={{ display: "flex", gap: 10 }}>
                          <button className="integrations-btn small" onClick={() => handleRunWorkflow(wf.id)}>⚡ Execute Now</button>
                          <button className="integrations-btn small danger" onClick={() => handleDeleteWorkflow(wf.id)}>Delete</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Webhooks */}
          {activeTab === "webhooks" && (
            <div className="integrations-panel-content" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
              <div>
                <h2 className="integrations-section-title">Register Webhook Endpoint</h2>
                <form className="integrations-form" onSubmit={handleCreateWebhook}>
                  <div className="integrations-form-row">
                    <label>Webhook Name</label>
                    <input className="integrations-input" type="text" placeholder="e.g. GitHub Push Events" value={newWebhook.name} onChange={e => setNewWebhook({ ...newWebhook, name: e.target.value })} required />
                  </div>
                  <div className="integrations-form-row">
                    <label>Direction</label>
                    <select className="integrations-select" value={newWebhook.direction} onChange={e => setNewWebhook({ ...newWebhook, direction: e.target.value })}>
                      <option value="incoming">Incoming (Collect events from outer tools)</option>
                      <option value="outgoing">Outgoing (Forward events to outer tools)</option>
                    </select>
                  </div>
                  {newWebhook.direction === "outgoing" && (
                    <div className="integrations-form-row">
                      <label>Target URL</label>
                      <input className="integrations-input" type="url" placeholder="https://api.mytool.com/webhook" value={newWebhook.url} onChange={e => setNewWebhook({ ...newWebhook, url: e.target.value })} required />
                    </div>
                  )}
                  <div className="integrations-form-row">
                    <label>Event Filters (comma separated)</label>
                    <input className="integrations-input" type="text" value={newWebhook.eventFilterCsv} onChange={e => setNewWebhook({ ...newWebhook, eventFilterCsv: e.target.value })} required />
                  </div>
                  <button className="integrations-btn" type="submit">Register Webhook</button>
                </form>
              </div>

              <div>
                <h2 className="integrations-section-title">Configured Endpoints</h2>
                {webhooks.length === 0 ? (
                  <div style={{ padding: "40px 0", textAlign: "center", color: "#94a3b8" }}>No webhooks registered.</div>
                ) : (
                  <div className="integrations-grid" style={{ gridTemplateColumns: "1fr", margin: 0 }}>
                    {webhooks.map(wh => (
                      <div className="integrations-card" key={wh.id} style={{ gap: 12 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <h4 style={{ margin: 0 }}>{wh.name}</h4>
                          <span className={`integrations-badge ${wh.direction === "incoming" ? "success" : "info"}`}>{wh.direction}</span>
                        </div>
                        <div style={{ fontSize: 12, background: "#0f172a", padding: 8, borderRadius: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                          {wh.direction === "incoming" ? (
                            <div>Webhook URI: <code>/api/v1/integrations/webhooks/incoming/{wh.id}</code></div>
                          ) : (
                            <div>Target URL: <code>{wh.url}</code></div>
                          )}
                          {wh.secret && (
                            <div>Signing Secret: <code>{wh.secret}</code></div>
                          )}
                          <div>Filters: {wh.event_filter.join(", ")}</div>
                        </div>
                        <button className="integrations-btn small danger" style={{ alignSelf: "flex-start" }} onClick={() => handleDeleteWebhook(wh.id)}>Delete</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Scheduler Jobs */}
          {activeTab === "scheduler" && (
            <div className="integrations-panel-content" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
              <div>
                <h2 className="integrations-section-title">Schedule Job</h2>
                <form className="integrations-form" onSubmit={handleCreateJob}>
                  <div className="integrations-form-row">
                    <label>Job Name</label>
                    <input className="integrations-input" type="text" placeholder="e.g. Midnight Sync Run" value={newJob.name} onChange={e => setNewJob({ ...newJob, name: e.target.value })} required />
                  </div>
                  <div className="integrations-form-row">
                    <label>Job Type</label>
                    <select className="integrations-select" value={newJob.jobType} onChange={e => setNewJob({ ...newJob, jobType: e.target.value })}>
                      <option value="connector_sync">Connector Sync (synchronize databases)</option>
                      <option value="agent_run">Trigger Agent Workspace check</option>
                      <option value="db_cleanup">Compliance Database Cleanup</option>
                    </select>
                  </div>
                  <div className="integrations-form-row">
                    <label>Schedule (Cron expression or interval)</label>
                    <input className="integrations-input" type="text" placeholder="e.g. 0 0 * * * or 1h" value={newJob.schedule} onChange={e => setNewJob({ ...newJob, schedule: e.target.value })} required />
                  </div>
                  <div className="integrations-form-row">
                    <label>Arguments (JSON payload)</label>
                    <textarea className="integrations-textarea" value={newJob.configJson} onChange={e => setNewJob({ ...newJob, configJson: e.target.value })} />
                  </div>
                  <button className="integrations-btn" type="submit">Schedule Trigger</button>
                </form>
              </div>

              <div>
                <h2 className="integrations-section-title">Active Timers &amp; Jobs</h2>
                {scheduledJobs.length === 0 ? (
                  <div style={{ padding: "40px 0", textAlign: "center", color: "#94a3b8" }}>No active timers scheduled.</div>
                ) : (
                  <div className="integrations-table-container">
                    <table className="integrations-table">
                      <thead>
                        <tr>
                          <th>Job</th>
                          <th>Type</th>
                          <th>Schedule</th>
                          <th>Next Run</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scheduledJobs.map(j => (
                          <tr key={j.id}>
                            <td><strong>{j.name}</strong></td>
                            <td><code>{j.job_type}</code></td>
                            <td><code>{j.schedule}</code></td>
                            <td>{j.next_run_at ? new Date(j.next_run_at).toLocaleString() : "Unknown"}</td>
                            <td>
                              <button className="integrations-btn small danger" onClick={() => handleDeleteJob(j.id)}>Delete</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* MCP Servers */}
          {activeTab === "mcp" && (
            <div className="integrations-panel-content" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
              <div>
                <h2 className="integrations-section-title">Register MCP Server</h2>
                <form className="integrations-form" onSubmit={handleRegisterMcp}>
                  <div className="integrations-form-row">
                    <label>Server Name</label>
                    <input className="integrations-input" type="text" placeholder="e.g. Filesystem Provider" value={newMcp.name} onChange={e => setNewMcp({ ...newMcp, name: e.target.value })} required />
                  </div>
                  <div className="integrations-form-row">
                    <label>Server Endpoint URL</label>
                    <input className="integrations-input" type="url" placeholder="http://localhost:8000/mcp" value={newMcp.serverUrl} onChange={e => setNewMcp({ ...newMcp, serverUrl: e.target.value })} required />
                  </div>
                  <div className="integrations-form-row">
                    <label>Transport Protocol</label>
                    <select className="integrations-select" value={newMcp.transport} onChange={e => setNewMcp({ ...newMcp, transport: e.target.value })}>
                      <option value="sse">SSE (Server-Sent Events)</option>
                      <option value="stdio">stdio (Local Command Pipeline)</option>
                    </select>
                  </div>
                  <div className="integrations-form-row">
                    <label>Auth Config Headers (JSON)</label>
                    <textarea className="integrations-textarea" value={newMcp.authConfigJson} onChange={e => setNewMcp({ ...newMcp, authConfigJson: e.target.value })} />
                  </div>
                  <button className="integrations-btn" type="submit">Bridge MCP Server</button>
                </form>
              </div>

              <div>
                <h2 className="integrations-section-title">Active MCP Servers</h2>
                {mcpServers.length === 0 ? (
                  <div style={{ padding: "40px 0", textAlign: "center", color: "#94a3b8" }}>No external Model Context Protocol servers bridged.</div>
                ) : (
                  <div className="integrations-table-container">
                    <table className="integrations-table">
                      <thead>
                        <tr>
                          <th>Server</th>
                          <th>Endpoint</th>
                          <th>Transport</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mcpServers.map(m => (
                          <tr key={m.id}>
                            <td><strong>{m.name}</strong></td>
                            <td><code>{m.server_url}</code></td>
                            <td>{m.transport}</td>
                            <td>
                              <span className={`integrations-badge ${m.health === "healthy" ? "success" : "warning"}`}>{m.status}</span>
                            </td>
                            <td>
                              <button className="integrations-btn small danger" onClick={() => handleDeleteMcp(m.id)}>Remove</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Real-time Events Log */}
          {activeTab === "events" && (
            <div className="integrations-panel-content">
              <h2 className="integrations-section-title">Subsystem Event Log</h2>
              <p className="integrations-section-desc">Real-time system events generated by agents, webhooks, and synchronization runs.</p>
              {integrationEvents.length === 0 ? (
                <div style={{ padding: "40px 0", textAlign: "center", color: "#94a3b8" }}>No active events logged in this workspace context.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {integrationEvents.map(e => (
                    <div className="integrations-card" key={e.id} style={{ display: "block" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <span className="integrations-badge success" style={{ fontFamily: "monospace" }}>{e.event_type}</span>
                        <span style={{ fontSize: 11, color: "#94a3b8" }}>{new Date(e.created_at).toLocaleString()}</span>
                      </div>
                      <pre style={{ margin: 0, fontSize: 12, background: "#0f172a", padding: 12, borderRadius: 8, overflowX: "auto" }}>
                        {JSON.stringify(e.payload, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </main>
      )}

      {/* Modals */}
      {installingConnector && (
        <div className="integrations-modal-overlay" onClick={() => setInstallingConnector(null)}>
          <div className="integrations-modal" onClick={e => e.stopPropagation()}>
            <h3 className="integrations-modal-header">Install {installingConnector.name}</h3>
            <form onSubmit={handleInstall} className="integrations-form">
              <div className="integrations-form-row">
                <label>Display Name</label>
                <input className="integrations-input" type="text" value={connDisplayName} onChange={e => setConnDisplayName(e.target.value)} required />
              </div>
              <div className="integrations-form-row">
                <label>Configuration JSON</label>
                <textarea className="integrations-textarea" value={connConfigJson} onChange={e => setConnConfigJson(e.target.value)} rows={4} />
              </div>
              <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: 12 }}>
                <button className="integrations-btn secondary" type="button" onClick={() => setInstallingConnector(null)}>Cancel</button>
                <button className="integrations-btn" type="submit">Verify &amp; Install</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {configuringAuth && (
        <div className="integrations-modal-overlay" onClick={() => setConfiguringAuth(null)}>
          <div className="integrations-modal" onClick={e => e.stopPropagation()}>
            <h3 className="integrations-modal-header">Authenticate {configuringAuth.display_name}</h3>
            <form onSubmit={handleConfigureAuth} className="integrations-form">
              <div className="integrations-form-row">
                <label>Authentication Type</label>
                <select className="integrations-select" value={authType} onChange={e => setAuthType(e.target.value)}>
                  <option value="oauth2">OAuth 2.0 Authorization</option>
                  <option value="api_key">Static API Secret Key</option>
                  <option value="token">Bearer access token</option>
                </select>
              </div>
              <div className="integrations-form-row">
                <label>Credentials payload (JSON)</label>
                <textarea className="integrations-textarea" value={authCredsJson} onChange={e => setAuthCredsJson(e.target.value)} rows={4} required />
              </div>
              <div className="integrations-form-row">
                <label>Scopes (comma separated)</label>
                <input className="integrations-input" type="text" placeholder="e.g. drive.readonly, userinfo.email" onChange={e => setAuthScopes(e.target.value.split(",").map(s => s.trim()))} />
              </div>
              <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: 12 }}>
                <button className="integrations-btn secondary" type="button" onClick={() => setConfiguringAuth(null)}>Cancel</button>
                <button className="integrations-btn" type="submit">Verify Credentials</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {browsingInstance && (
        <div className="integrations-modal-overlay" onClick={() => setBrowsingInstance(null)}>
          <div className="integrations-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 800 }}>
            <h3 className="integrations-modal-header">Browse Folder: {browsingInstance.display_name}</h3>
            <div className="integrations-modal-body">
              <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
                <input className="integrations-input" type="text" style={{ flex: 1 }} value={browsedPath} onChange={e => setBrowsedPath(e.target.value)} />
                <button className="integrations-btn" onClick={() => handleBrowseConnector(browsingInstance.id, browsedPath)}>Go</button>
              </div>
              {browsedLoading ? (
                <div>Loading items...</div>
              ) : browsedItems.length === 0 ? (
                <div style={{ textAlign: "center", padding: 24, color: "#94a3b8" }}>Folder path is empty.</div>
              ) : (
                <div className="integrations-table-container">
                  <table className="integrations-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Path</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {browsedItems.map(item => (
                        <tr key={item.id}>
                          <td><strong>{item.name}</strong></td>
                          <td>
                            <span className={`integrations-badge ${item.type === "folder" ? "info" : "success"}`}>
                              {item.type}
                            </span>
                          </td>
                          <td><code>{item.path}</code></td>
                          <td>
                            {item.type === "folder" && (
                              <button className="integrations-btn small secondary" onClick={() => handleBrowseConnector(browsingInstance.id, item.path)}>
                                Open
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
              <button className="integrations-btn secondary" onClick={() => setBrowsingInstance(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
