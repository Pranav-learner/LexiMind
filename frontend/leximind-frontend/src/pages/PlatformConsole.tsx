import { useState, useEffect } from "react";
import type {
  ProviderStatus,
  PlatformMetrics,
  FeatureFlagRule,
  PlatformOpsLog
} from "../api/platform";
import {
  getPlatformHealth,
  getPlatformMetrics,
  scaleService,
  getFeatureFlags,
  updateFlagRollout,
  createFlagOverride,
  triggerPlatformBackup,
  triggerPlatformRestore,
  getPlatformOpsLogs
} from "../api/platform";
import "../styles/platform.css";

export default function PlatformConsole() {
  const [activeTab, setActiveTab] = useState<"infra" | "workers" | "flags" | "backup" | "logs">("infra");
  const [healthData, setHealthData] = useState<ProviderStatus[]>([]);
  const [metrics, setMetrics] = useState<PlatformMetrics | null>(null);
  const [flags, setFlags] = useState<Record<string, FeatureFlagRule>>({});
  const [logs, setLogs] = useState<PlatformOpsLog[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Backup form state
  const [snapshotName, setSnapshotName] = useState<string>("manual-backup");
  // Restore state
  const [restoreId, setRestoreId] = useState<string>("");
  // Scaling state
  const [selectedService, setSelectedService] = useState<string>("leximind-api");
  const [replicasCount, setReplicasCount] = useState<number>(3);
  // Rollout state
  const [selectedFlag, setSelectedFlag] = useState<string>("enable_canary");
  const [rolloutPercentage, setRolloutPercentage] = useState<number>(20);
  // Override state
  const [overrideKey, setOverrideKey] = useState<string>("");
  const [overrideVal, setOverrideVal] = useState<boolean>(true);

  const loadData = async () => {
    try {
      setLoading(true);
      const [health, met, flg, lg] = await Promise.all([
        getPlatformHealth(),
        getPlatformMetrics(),
        getFeatureFlags(),
        getPlatformOpsLogs()
      ]);
      setHealthData(health);
      setMetrics(met);
      setFlags(flg);
      setLogs(lg);
    } catch (err) {
      console.error("Failed to load platform operations console data", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(() => {
      getPlatformMetrics().then(setMetrics).catch(console.error);
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleScale = async () => {
    try {
      setActionMessage("Scaling service...");
      const res = await scaleService(selectedService, replicasCount);
      setActionMessage(res.message || "Scale request submitted.");
      await loadData();
    } catch (err: any) {
      setActionMessage(`Error: ${err.message || "Failed to scale"}`);
    }
  };

  const handleUpdateRollout = async () => {
    try {
      setActionMessage("Updating flag percentage rollout...");
      const res = await updateFlagRollout(selectedFlag, rolloutPercentage);
      setActionMessage(res.message || "Rollout percentage updated.");
      await loadData();
    } catch (err: any) {
      setActionMessage(`Error: ${err.message || "Failed to update flag"}`);
    }
  };

  const handleCreateOverride = async () => {
    if (!overrideKey.trim()) return;
    try {
      setActionMessage("Configuring flag override...");
      const res = await createFlagOverride(selectedFlag, overrideKey.trim(), overrideVal);
      setActionMessage(res.message || "Override successfully applied.");
      await loadData();
    } catch (err: any) {
      setActionMessage(`Error: ${err.message || "Failed to save override"}`);
    }
  };

  const handleTriggerBackup = async () => {
    try {
      setActionMessage("Taking system snapshot...");
      const res = await triggerPlatformBackup(snapshotName);
      setActionMessage(`Backup Successful! Snapshot ID: ${res.snapshot_id} (Size: ${(res.size_bytes / 1024 / 1024).toFixed(2)} MB)`);
      await loadData();
    } catch (err: any) {
      setActionMessage(`Error: ${err.message || "Backup failed"}`);
    }
  };

  const handleTriggerRestore = async () => {
    if (!restoreId.trim()) return;
    try {
      setActionMessage("Restoring system snapshot...");
      const res = await triggerPlatformRestore(restoreId.trim());
      setActionMessage(res.details || "System restored successfully.");
      await loadData();
    } catch (err: any) {
      setActionMessage(`Error: ${err.message || "Restore failed"}`);
    }
  };

  return (
    <div className="platform-console-container">
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2rem" }}>
        <div>
          <h1 style={{ fontSize: "2.25rem", margin: 0, fontWeight: 800 }} className="platform-title-glow">
            LexiMind Enterprise Console
          </h1>
          <p style={{ color: "#94a3b8", marginTop: "0.25rem" }}>
            Operational infrastructure administration, horizontal scaling, canary rollouts, and disaster recovery.
          </p>
        </div>
        <button className="platform-btn" onClick={loadData}>
          Refresh Console
        </button>
      </div>

      {/* Quick Ops status banner */}
      {actionMessage && (
        <div className="platform-glass-panel" style={{ marginBottom: "1.5rem", borderLeft: "4px solid #6366f1", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong style={{ color: "#818cf8" }}>Operations Signal:</strong> {actionMessage}
          </div>
          <button style={{ background: "none", border: "none", color: "#94a3b8", cursor: "pointer" }} onClick={() => setActionMessage(null)}>
            ✕
          </button>
        </div>
      )}

      {/* Metrics Row */}
      {metrics && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1.25rem", marginBottom: "2rem" }}>
          <div className="platform-metric-card">
            <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>GPU Utilization</span>
            <span className="platform-metric-value" style={{ color: "#ec4899" }}>
              {(metrics.gpu_utilization * 100).toFixed(0)}%
            </span>
            <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
              {metrics.gpu_slots_active}/{metrics.gpu_slots_max} Active Slots
            </span>
          </div>

          <div className="platform-metric-card">
            <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>CPU Utilization</span>
            <span className="platform-metric-value" style={{ color: "#a855f7" }}>
              {(metrics.cpu_utilization * 100).toFixed(0)}%
            </span>
            <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
              {metrics.cpu_slots_active}/{metrics.cpu_slots_max} Active Slots
            </span>
          </div>

          <div className="platform-metric-card">
            <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>DB Connection Pool</span>
            <span className="platform-metric-value" style={{ color: "#3b82f6" }}>
              {metrics.active_connections_db}
            </span>
            <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Active PostgreSQL Conns</span>
          </div>

          <div className="platform-metric-card">
            <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>Task Backlog Queue</span>
            <span className="platform-metric-value" style={{ color: "#22c55e" }}>
              {metrics.queue_backlog_total}
            </span>
            <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Jobs Pending Dispatch</span>
          </div>

          <div className="platform-metric-card">
            <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>AI Resource Backlog</span>
            <span className="platform-metric-value" style={{ color: "#eab308" }}>
              {metrics.backlog_waiting_count}
            </span>
            <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Tasks Waiting Resource</span>
          </div>
        </div>
      )}

      {/* Tabs Layout */}
      <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem" }}>
        <button
          className={`platform-btn ${activeTab !== "infra" ? "inactive" : ""}`}
          style={{ background: activeTab === "infra" ? undefined : "rgba(30, 41, 59, 0.4)", boxShadow: activeTab === "infra" ? undefined : "none" }}
          onClick={() => setActiveTab("infra")}
        >
          Registry Health Status
        </button>
        <button
          className={`platform-btn ${activeTab !== "workers" ? "inactive" : ""}`}
          style={{ background: activeTab === "workers" ? undefined : "rgba(30, 41, 59, 0.4)", boxShadow: activeTab === "workers" ? undefined : "none" }}
          onClick={() => setActiveTab("workers")}
        >
          Specialist Worker Pools
        </button>
        <button
          className={`platform-btn ${activeTab !== "flags" ? "inactive" : ""}`}
          style={{ background: activeTab === "flags" ? undefined : "rgba(30, 41, 59, 0.4)", boxShadow: activeTab === "flags" ? undefined : "none" }}
          onClick={() => setActiveTab("flags")}
        >
          Policy Feature Flags
        </button>
        <button
          className={`platform-btn ${activeTab !== "backup" ? "inactive" : ""}`}
          style={{ background: activeTab === "backup" ? undefined : "rgba(30, 41, 59, 0.4)", boxShadow: activeTab === "backup" ? undefined : "none" }}
          onClick={() => setActiveTab("backup")}
        >
          Disaster Recovery & Backup
        </button>
        <button
          className={`platform-btn ${activeTab !== "logs" ? "inactive" : ""}`}
          style={{ background: activeTab === "logs" ? undefined : "rgba(30, 41, 59, 0.4)", boxShadow: activeTab === "logs" ? undefined : "none" }}
          onClick={() => setActiveTab("logs")}
        >
          Operations Telemetry logs
        </button>
      </div>

      {/* Tab Panels */}
      {loading ? (
        <div className="platform-glass-panel" style={{ textAlign: "center", padding: "3rem" }}>
          <div style={{ display: "inline-block", width: "40px", height: "40px", border: "4px solid rgba(255,255,255,0.1)", borderTopColor: "#6366f1", borderRadius: "50%", animation: "spin 1s linear infinite" }}></div>
          <p style={{ marginTop: "1rem", color: "#94a3b8" }}>Aggregating cluster infrastructure telemetry...</p>
        </div>
      ) : (
        <div>
          {/* TAB 1: INFRASTRUCTURE STATUS */}
          {activeTab === "infra" && (
            <div className="platform-glass-panel">
              <h3 style={{ margin: "0 0 1.25rem 0", fontSize: "1.25rem" }}>Registered Infrastructure Providers</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {healthData.map((provider) => (
                  <div
                    key={provider.name}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "1rem",
                      background: "rgba(15,23,42,0.3)",
                      borderRadius: "8px",
                      border: "1px solid rgba(255,255,255,0.03)"
                    }}
                  >
                    <div>
                      <strong style={{ fontSize: "1rem" }}>{provider.name}</strong>
                      <div style={{ color: "#94a3b8", fontSize: "0.85rem", marginTop: "0.25rem" }}>{provider.details}</div>
                    </div>
                    <span className={`platform-status-badge status-${provider.status}`}>
                      {provider.status.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 2: SPECIALIST WORKERS */}
          {activeTab === "workers" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
              <div className="platform-glass-panel">
                <h3 style={{ margin: "0 0 1rem 0" }}>Scale Worker Replicas</h3>
                <p style={{ color: "#94a3b8", fontSize: "0.85rem", marginBottom: "1.5rem" }}>
                  Set replica targets. Scale API nodes, specialized background schedulers, or data parsers.
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                  <div>
                    <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.85rem", color: "#94a3b8" }}>Target Service Pool</label>
                    <select
                      style={{ width: "100%", padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                      value={selectedService}
                      onChange={(e) => setSelectedService(e.target.value)}
                    >
                      <option value="leximind-api">leximind-api (API Gateway)</option>
                      <option value="leximind-worker-api">leximind-worker-api (API Task Pool)</option>
                      <option value="leximind-worker-embedding">leximind-worker-embedding (Embedding Vectorizer)</option>
                      <option value="leximind-worker-media">leximind-worker-media (Media Transcriber)</option>
                      <option value="leximind-worker-graph">leximind-worker-graph (Knowledge Graph Build)</option>
                      <option value="leximind-worker-agent">leximind-worker-agent (Agent Executor)</option>
                      <option value="leximind-worker-evaluation">leximind-worker-evaluation (Evaluation Pool)</option>
                      <option value="leximind-worker-learning">leximind-worker-learning (Continuous Learning)</option>
                      <option value="leximind-worker-optimization">leximind-worker-optimization (Model Router Optimizers)</option>
                      <option value="leximind-worker-automation">leximind-worker-automation (Webhooks/Automations)</option>
                      <option value="leximind-worker-scheduler">leximind-worker-scheduler (Central Schedulers)</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.85rem", color: "#94a3b8" }}>Target Replica Count</label>
                    <input
                      type="number"
                      min={0}
                      max={20}
                      style={{ width: "100%", padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                      value={replicasCount}
                      onChange={(e) => setReplicasCount(Number(e.target.value))}
                    />
                  </div>

                  <button className="platform-btn" onClick={handleScale}>
                    Commit Scale Command
                  </button>
                </div>
              </div>

              <div className="platform-glass-panel">
                <h3 style={{ margin: "0 0 1.25rem 0" }}>Active Orchestration Clusters</h3>
                <p style={{ color: "#94a3b8", fontSize: "0.85rem" }}>
                  Deployment replicas resolved from standard Orchestrator Providers (Docker Compose / Kubernetes HPAs).
                </p>
                <div style={{ fontFamily: "monospace", padding: "1rem", background: "#0f172a", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.05)", maxHeight: "250px", overflowY: "auto" }}>
                  <div style={{ color: "#34d399" }}>$ kubectl get deployments -n leximind</div>
                  <div style={{ color: "#94a3b8", marginTop: "0.5rem" }}>
                    leximind-api            3/3-pods active (healthy)
                    <br />
                    leximind-worker         2/2-pods active (healthy)
                    <br />
                    postgres-db-replica     1/1-pods active (healthy)
                    <br />
                    redis-cluster-cache     3/3-pods active (healthy)
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: FEATURE FLAGS */}
          {activeTab === "flags" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
              <div className="platform-glass-panel">
                <h3 style={{ margin: "0 0 1.25rem 0" }}>Feature Flag Control Panel</h3>
                
                <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                  <div>
                    <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.85rem", color: "#94a3b8" }}>Target Feature Flag</label>
                    <select
                      style={{ width: "100%", padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                      value={selectedFlag}
                      onChange={(e) => {
                        setSelectedFlag(e.target.value);
                        setRolloutPercentage(flags[e.target.value]?.percentage || 100);
                      }}
                    >
                      {Object.keys(flags).map(name => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem", fontSize: "0.85rem", color: "#94a3b8" }}>
                      <span>Rollout Rate</span>
                      <span>{rolloutPercentage}%</span>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      style={{ width: "100%" }}
                      value={rolloutPercentage}
                      onChange={(e) => setRolloutPercentage(Number(e.target.value))}
                    />
                  </div>

                  <button className="platform-btn" onClick={handleUpdateRollout}>
                    Update Rollout Rate
                  </button>

                  <hr style={{ border: "none", borderTop: "1px solid rgba(255,255,255,0.05)", margin: "0.5rem 0" }} />

                  <div>
                    <h4 style={{ margin: "0 0 0.75rem 0" }}>Target Specific Override</h4>
                    <div style={{ display: "flex", gap: "0.75rem" }}>
                      <input
                        type="text"
                        placeholder="User/Org/Workspace UUID"
                        style={{ flex: 1, padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                        value={overrideKey}
                        onChange={(e) => setOverrideKey(e.target.value)}
                      />
                      <select
                        style={{ padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                        value={String(overrideVal)}
                        onChange={(e) => setOverrideVal(e.target.value === "true")}
                      >
                        <option value="true">Enable</option>
                        <option value="false">Disable</option>
                      </select>
                    </div>
                  </div>

                  <button className="platform-btn" style={{ background: "linear-gradient(135deg, #10b981 0%, #059669 100%)", boxShadow: "0 4px 14px rgba(16, 185, 129, 0.3)" }} onClick={handleCreateOverride}>
                    Save Target Override
                  </button>
                </div>
              </div>

              <div className="platform-glass-panel">
                <h3 style={{ margin: "0 0 1.25rem 0" }}>Active Flag Configurations</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "1rem", maxHeight: "400px", overflowY: "auto" }}>
                  {Object.entries(flags).map(([name, spec]) => (
                    <div key={name} style={{ padding: "1rem", background: "rgba(15,23,42,0.3)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.02)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong style={{ color: "#a855f7" }}>{name}</strong>
                        <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>{spec.percentage}% Rollout</span>
                      </div>
                      <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.5rem" }}>
                        Default: {spec.default ? "Enabled" : "Disabled"}
                        {Object.keys(spec.overrides).length > 0 && (
                          <div style={{ marginTop: "0.25rem", color: "#818cf8" }}>
                            Active Overrides: {Object.keys(spec.overrides).length} configured keys.
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: DISASTER RECOVERY & BACKUP */}
          {activeTab === "backup" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
              <div className="platform-glass-panel">
                <h3 style={{ margin: "0 0 1rem 0" }}>Trigger System Backup</h3>
                <p style={{ color: "#94a3b8", fontSize: "0.85rem", marginBottom: "1.5rem" }}>
                  Initiates a complete hot backup of the active SQL database, FAISS index files, and configurations meta files.
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                  <div>
                    <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.85rem", color: "#94a3b8" }}>Snapshot Label</label>
                    <input
                      type="text"
                      style={{ width: "100%", padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                      value={snapshotName}
                      onChange={(e) => setSnapshotName(e.target.value)}
                    />
                  </div>

                  <button className="platform-btn" onClick={handleTriggerBackup}>
                    Execute Snapshot Backup
                  </button>
                </div>
              </div>

              <div className="platform-glass-panel">
                <h3 style={{ margin: "0 0 1rem 0" }}>Point-in-Time Restore</h3>
                <p style={{ color: "#94a3b8", fontSize: "0.85rem", marginBottom: "1.5rem" }}>
                  Restore the cluster databases and vector assets back to a previous snapshot ID state (recovery playbook).
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                  <div>
                    <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.85rem", color: "#94a3b8" }}>Snapshot ID</label>
                    <input
                      type="text"
                      placeholder="e.g. snap_dfd120ab"
                      style={{ width: "100%", padding: "0.75rem", background: "#1e293b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", color: "#fff" }}
                      value={restoreId}
                      onChange={(e) => setRestoreId(e.target.value)}
                    />
                  </div>

                  <button className="platform-btn" style={{ background: "linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)", boxShadow: "0 4px 14px rgba(239, 68, 68, 0.3)" }} onClick={handleTriggerRestore}>
                    Confirm System Restore
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* TAB 5: LOGS */}
          {activeTab === "logs" && (
            <div className="platform-glass-panel">
              <h3 style={{ margin: "0 0 1.25rem 0", fontSize: "1.25rem" }}>Platform Operations Audit Logs</h3>
              <div style={{ background: "#0b0f19", border: "1px solid rgba(255,255,255,0.05)", borderRadius: "8px", maxHeight: "400px", overflowY: "auto" }}>
                {logs.length === 0 ? (
                  <div style={{ padding: "2rem", textAlign: "center", color: "#64748b" }}>
                    No operations telemetry logged. Try trigger a scale or backup operation first.
                  </div>
                ) : (
                  logs.map((log) => (
                    <div className="platform-log-entry" key={log.id}>
                      <span style={{ color: "#818cf8" }}>[{new Date(log.created_at).toLocaleString()}]</span>{" "}
                      <span style={{ color: log.status === "error" ? "#f87171" : log.status === "warning" ? "#fbbf24" : "#34d399", fontWeight: "bold" }}>
                        {log.event_type}
                      </span>{" "}
                      <span style={{ color: "#38bdf8" }}>({log.service_name})</span>: {log.message}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
