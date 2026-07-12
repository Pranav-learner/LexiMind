// Knowledge Graph Inspector (Phase 7, Module 1) — developer tools for the semantic graph.
// Entity explorer + details, relationship explorer, graph statistics, validation report, and build logs.
// (The interactive visual graph UI is Module 4; this is the inspection/debug surface.)
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  buildWorkspaceGraph, entityColor, getEntity, graphStats, listGraphLogs, searchEntities,
  searchRelationships, validateGraph,
  type EntityDetail, type GraphEntity, type GraphLog, type GraphRelationship, type GraphStats,
  type ValidationReport,
} from "../api/knowledge";
import "../styles/knowledge.css";

type Tab = "entities" | "relationships" | "stats" | "validation" | "logs";

export default function KnowledgeGraphInspector() {
  const { workspaceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("entities");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [selected, setSelected] = useState<EntityDetail | null>(null);
  const [rels, setRels] = useState<GraphRelationship[]>([]);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [logs, setLogs] = useState<GraphLog[]>([]);
  const [error, setError] = useState("");
  const [building, setBuilding] = useState(false);

  const loadEntities = useCallback(async () => {
    try { setEntities(await searchEntities(workspaceId, { query: query || undefined, type: typeFilter || undefined, limit: 100 })); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load entities."); }
  }, [workspaceId, query, typeFilter]);

  const loadAll = useCallback(async () => {
    try {
      setStats(await graphStats(workspaceId));
      setLogs(await listGraphLogs(workspaceId));
    } catch { /* ignore */ }
  }, [workspaceId]);

  useEffect(() => { loadEntities(); }, [loadEntities]);
  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { if (tab === "relationships") searchRelationships(workspaceId).then(setRels).catch(() => {}); }, [tab, workspaceId]);
  useEffect(() => { if (tab === "validation") validateGraph(workspaceId).then(setValidation).catch(() => {}); }, [tab, workspaceId]);

  async function build() {
    setBuilding(true); setError("");
    try { await buildWorkspaceGraph(workspaceId); await loadEntities(); await loadAll(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Build failed."); }
    finally { setBuilding(false); }
  }
  async function openEntity(id: string) {
    try { setSelected(await getEntity(workspaceId, id)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load entity."); }
  }

  return (
    <div className="kg-page">
      <header className="kg-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🕸️ Knowledge Graph</h1>
        <button className="kg-build" disabled={building} onClick={build}>
          {building ? "Building…" : "Rebuild graph"}
        </button>
      </header>

      {stats && (
        <div className="kg-stats-bar">
          <span><b>{stats.entities}</b> entities</span>
          <span><b>{stats.relationships}</b> relationships</span>
          <span><b>{stats.merged_entities}</b> merged</span>
          <span>density <b>{stats.density}</b></span>
        </div>
      )}
      {error && <p className="kg-error">{error}</p>}

      <nav className="kg-tabs">
        {(["entities", "relationships", "stats", "validation", "logs"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>

      {tab === "entities" && (
        <div className="kg-grid">
          <div className="kg-list-panel">
            <div className="kg-filters">
              <input value={query} placeholder="Search entities…" onChange={(e) => setQuery(e.target.value)} />
              <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">all types</option>
                {stats && Object.keys(stats.entity_types).map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <ul className="kg-entities">
              {entities.length === 0 && <li className="kg-muted">No entities. Build the graph or extract text.</li>}
              {entities.map((e) => (
                <li key={e.id} className={selected?.id === e.id ? "is-active" : ""} onClick={() => openEntity(e.id)}>
                  <span className="kg-ent-type" style={{ background: entityColor(e.entity_type) }}>{e.entity_type}</span>
                  <span className="kg-ent-name">{e.canonical_name}</span>
                  <span className="kg-ent-meta">×{e.mention_count} · deg {e.degree}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="kg-detail-panel">
            {!selected && <div className="kg-empty">Select an entity to inspect its aliases, provenance and relationships.</div>}
            {selected && (
              <>
                <h2><span className="kg-ent-type" style={{ background: entityColor(selected.entity_type) }}>{selected.entity_type}</span> {selected.canonical_name}</h2>
                <div className="kg-detail-meta">
                  confidence {Math.round(selected.confidence * 100)}% · {selected.mention_count} mentions · v{selected.version}
                </div>
                {selected.aliases.length > 0 && <p><b>Aliases:</b> {selected.aliases.join(", ")}</p>}
                <p className="kg-muted"><b>Provenance:</b> {selected.source_refs.length} source reference(s)</p>
                <h4>Relationships ({selected.relationships.length})</h4>
                <ul className="kg-rels">
                  {selected.relationships.map((r) => (
                    <li key={r.id}>
                      <span className="kg-rel-type">{r.rel_type}</span>
                      <span className="kg-rel-edge">
                        {r.source_id === selected.id ? `→ ${r.target_name}` : `← ${r.source_name}`}
                      </span>
                      <span className="kg-rel-w">w {r.weight.toFixed(2)}</span>
                    </li>
                  ))}
                  {selected.relationships.length === 0 && <li className="kg-muted">No relationships.</li>}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

      {tab === "relationships" && (
        <table className="kg-table">
          <thead><tr><th>Source</th><th>Type</th><th>Target</th><th>Weight</th><th>Mentions</th></tr></thead>
          <tbody>
            {rels.map((r) => (
              <tr key={r.id}>
                <td>{r.source_name}</td><td><span className="kg-rel-type">{r.rel_type}</span></td>
                <td>{r.target_name}</td><td>{r.weight.toFixed(2)}</td><td>{r.mention_count}</td>
              </tr>
            ))}
            {rels.length === 0 && <tr><td colSpan={5} className="kg-muted">No relationships.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "stats" && stats && (
        <div className="kg-stats-detail">
          <div>
            <h4>Entity types</h4>
            {Object.entries(stats.entity_types).map(([t, n]) => (
              <div className="kg-bar-row" key={t}>
                <span className="kg-bar-label"><span className="kg-dot" style={{ background: entityColor(t) }} />{t}</span>
                <span className="kg-bar"><span className="kg-bar-fill" style={{ width: `${Math.min(100, n * 12)}px`, background: entityColor(t) }} /></span>
                <span>{n}</span>
              </div>
            ))}
          </div>
          <div>
            <h4>Relationship types</h4>
            {Object.entries(stats.relationship_types).map(([t, n]) => (
              <div className="kg-bar-row" key={t}><span className="kg-bar-label">{t}</span><span>{n}</span></div>
            ))}
          </div>
        </div>
      )}

      {tab === "validation" && validation && (
        <div className="kg-validation">
          <p className={validation.ok ? "kg-ok" : "kg-bad"}>
            {validation.ok ? "✓ Graph integrity OK" : `✕ ${validation.error_count} error(s)`} · {validation.warning_count} warning(s)
          </p>
          {validation.errors.map((e, i) => <div className="kg-issue kg-issue-err" key={i}><b>{e.kind}</b> {e.detail}</div>)}
          {validation.warnings.map((w, i) => <div className="kg-issue kg-issue-warn" key={i}><b>{w.kind}</b> {w.detail}</div>)}
        </div>
      )}

      {tab === "logs" && (
        <table className="kg-table">
          <thead><tr><th>Scope</th><th>Status</th><th>Entities (new/merged)</th><th>Rels</th><th>Errors</th><th>ms</th></tr></thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.id}>
                <td>{l.scope}</td><td>{l.status}</td>
                <td>{l.entities_created} / {l.entities_merged}</td>
                <td>{l.relationships_created}</td><td>{l.validation_errors}</td><td>{Math.round(l.processing_ms)}</td>
              </tr>
            ))}
            {logs.length === 0 && <tr><td colSpan={6} className="kg-muted">No builds yet.</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
