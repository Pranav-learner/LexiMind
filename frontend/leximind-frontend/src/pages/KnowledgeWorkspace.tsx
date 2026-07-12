// Interactive Knowledge Workspace (Phase 7, Module 4) — LexiMind's knowledge operating system.
// Hand-rolled SVG graph explorer (no viz lib) + entity/relationship panels + AI graph chat + timeline
// + analytics + controlled editing. Pure client over the /knowledge-workspace API (which reuses the
// Module 1-3 graph services + ChatService → single AnswerService).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError } from "../api/client";
import {
  analytics as fetchAnalytics, editGraph, entityColor, entityDetail,
  graphChat, graphView, knowledgeSearch, overview as fetchOverview, relationshipDetail, timeline as fetchTimeline,
  type Analytics, type EntityDetail, type GraphView, type Overview, type RelationshipDetail,
  type SearchResult, type TimelineEvent,
} from "../api/knowledgeWorkspace";
import "../styles/knowledgeworkspace.css";

type Tab = "graph" | "timeline" | "analytics" | "chat";
type ChatMsg = { role: "user" | "assistant"; text: string };

// deterministic radial layout (center = highest-degree node; others on rings) — no physics needed
function layout(view: GraphView): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {};
  const nodes = [...view.nodes].sort((a, b) => b.degree - a.degree);
  if (!nodes.length) return pos;
  pos[nodes[0].id] = { x: 0, y: 0 };
  const rest = nodes.slice(1);
  const perRing = 12;
  rest.forEach((n, i) => {
    const ring = Math.floor(i / perRing) + 1;
    const inRing = i % perRing;
    const count = Math.min(perRing, rest.length - (ring - 1) * perRing);
    const angle = (inRing / count) * Math.PI * 2 + ring * 0.4;
    const r = 130 * ring;
    pos[n.id] = { x: Math.cos(angle) * r, y: Math.sin(angle) * r };
  });
  return pos;
}

export default function KnowledgeWorkspace() {
  const { workspaceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("graph");
  const [ov, setOv] = useState<Overview | null>(null);
  const [view, setView] = useState<GraphView | null>(null);
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [rel, setRel] = useState<RelationshipDetail | null>(null);
  const [search, setSearch] = useState("");
  const [searchRes, setSearchRes] = useState<SearchResult | null>(null);
  const [tl, setTl] = useState<TimelineEvent[]>([]);
  const [an, setAn] = useState<Analytics | null>(null);
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [convId, setConvId] = useState<string | undefined>();
  const [typeFilter, setTypeFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [transform, setTransform] = useState({ tx: 0, ty: 0, k: 1 });
  const pan = useRef<{ x: number; y: number } | null>(null);

  const loadGraph = useCallback(async (seed?: string) => {
    try { setView(await graphView(workspaceId, seed ? { seed, hops: 1 } : { limit: 60 })); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load graph."); }
  }, [workspaceId]);

  useEffect(() => {
    fetchOverview(workspaceId).then(setOv).catch(() => {});
    loadGraph();
  }, [workspaceId, loadGraph]);
  useEffect(() => { if (tab === "timeline") fetchTimeline(workspaceId).then(setTl).catch(() => {}); }, [tab, workspaceId]);
  useEffect(() => { if (tab === "analytics") fetchAnalytics(workspaceId).then(setAn).catch(() => {}); }, [tab, workspaceId]);

  const pos = useMemo(() => (view ? layout(view) : {}), [view]);
  const nodes = useMemo(() => (view?.nodes ?? []).filter((n) => !typeFilter || n.type === typeFilter), [view, typeFilter]);
  const nodeIds = new Set(nodes.map((n) => n.id));

  async function selectEntity(id: string) {
    setRel(null);
    try { setEntity(await entityDetail(workspaceId, id)); } catch (e) { setError(e instanceof ApiError ? e.message : "Failed."); }
  }
  async function selectRel(id: string) {
    setEntity(null);
    try { setRel(await relationshipDetail(workspaceId, id)); } catch { /* ignore */ }
  }
  async function runSearch() {
    if (!search.trim()) return;
    try { setSearchRes(await knowledgeSearch(workspaceId, search)); } catch (e) { setError(e instanceof ApiError ? e.message : "Search failed."); }
  }
  async function sendChat() {
    if (!chatInput.trim()) return;
    const q = chatInput; setChatInput(""); setChat((c) => [...c, { role: "user", text: q }]); setBusy(true);
    try {
      const r = await graphChat(workspaceId, q, convId);
      setConvId(r.conversation_id);
      setChat((c) => [...c, { role: "assistant", text: r.answer }]);
    } catch (e) { setChat((c) => [...c, { role: "assistant", text: e instanceof ApiError ? e.message : "Chat failed." }]); }
    finally { setBusy(false); }
  }
  async function doEdit(op: string, params: Record<string, unknown>) {
    setBusy(true);
    try { await editGraph(workspaceId, op, params); await loadGraph(); fetchOverview(workspaceId).then(setOv); setEntity(null); setRel(null); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Edit failed."); }
    finally { setBusy(false); }
  }

  // pan/zoom
  function onWheel(e: React.WheelEvent) {
    const k = Math.min(3, Math.max(0.3, transform.k * (e.deltaY < 0 ? 1.1 : 0.9)));
    setTransform((t) => ({ ...t, k }));
  }
  function onDown(e: React.MouseEvent) { pan.current = { x: e.clientX - transform.tx, y: e.clientY - transform.ty }; }
  function onMove(e: React.MouseEvent) { if (pan.current) setTransform((t) => ({ ...t, tx: e.clientX - pan.current!.x, ty: e.clientY - pan.current!.y })); }
  function onUp() { pan.current = null; }

  return (
    <div className="kw-page">
      <header className="kw-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🌐 Knowledge Workspace</h1>
        {ov && <span className="kw-muted">{ov.entities} entities · {ov.relationships} relationships · density {ov.density}</span>}
        <Link to={`/workspace/${workspaceId}/reasoning`} className="kw-muted">Reasoning →</Link>
      </header>
      {error && <p className="kw-error" onClick={() => setError("")}>{error} ✕</p>}

      <div className="kw-body">
        {/* ---------- left: search + concepts + filters ---------- */}
        <aside className="kw-left">
          <div className="kw-search">
            <input value={search} placeholder="Search knowledge…" onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch()} />
          </div>
          {searchRes && (
            <div className="kw-search-res">
              <h4>Entities</h4>
              {searchRes.entities.map((e) => (
                <button key={e.id} className="kw-concept" onClick={() => { selectEntity(e.id); loadGraph(e.id); }}>
                  <span className="kw-dot" style={{ background: entityColor(e.type) }} />{e.name}
                </button>
              ))}
            </div>
          )}
          <h4>Top concepts</h4>
          <div className="kw-concepts">
            {ov?.top_concepts.map((c) => (
              <button key={c.id} className="kw-concept" onClick={() => { selectEntity(c.id); loadGraph(c.id); }}>
                <span className="kw-dot" style={{ background: entityColor(c.type) }} />{c.name}
                <span className="kw-deg">{c.degree}</span>
              </button>
            ))}
          </div>
          <h4>Filter by type</h4>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">all types</option>
            {ov && Object.keys(ov.entity_types).map((t) => <option key={t} value={t}>{t} ({ov.entity_types[t]})</option>)}
          </select>
          <button className="kw-reset" onClick={() => { loadGraph(); setTransform({ tx: 0, ty: 0, k: 1 }); }}>Reset view</button>
        </aside>

        {/* ---------- center: graph / timeline / analytics / chat ---------- */}
        <main className="kw-center">
          <nav className="kw-tabs">
            {(["graph", "timeline", "analytics", "chat"] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
            ))}
          </nav>

          {tab === "graph" && (
            <svg className="kw-graph" viewBox="-450 -320 900 640" onWheel={onWheel}
              onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
              <g transform={`translate(${transform.tx} ${transform.ty}) scale(${transform.k})`}>
                {(view?.edges ?? []).filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map((e) => {
                  const a = pos[e.source], b = pos[e.target]; if (!a || !b) return null;
                  return (
                    <g key={e.id} className="kw-edge" onClick={() => selectRel(e.id)}>
                      <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                        stroke={e.status === "inferred" ? "#c4b5fd" : "#cbd5e1"}
                        strokeDasharray={e.status === "inferred" ? "4 3" : undefined} strokeWidth={1 + e.weight} />
                      <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2} className="kw-edge-label">{e.type}</text>
                    </g>
                  );
                })}
                {nodes.map((n) => {
                  const p = pos[n.id]; if (!p) return null;
                  const r = 10 + Math.min(16, n.degree * 2);
                  const sel = entity?.id === n.id;
                  return (
                    <g key={n.id} transform={`translate(${p.x} ${p.y})`} className="kw-node"
                      onClick={() => selectEntity(n.id)} onDoubleClick={() => loadGraph(n.id)}>
                      <circle r={r} fill={entityColor(n.type)} stroke={sel ? "#1e293b" : "#fff"} strokeWidth={sel ? 3 : 1.5} />
                      <text y={r + 12} className="kw-node-label">{n.name}</text>
                    </g>
                  );
                })}
                {nodes.length === 0 && <text className="kw-empty-g">No graph yet — build one from the Knowledge Graph page.</text>}
              </g>
            </svg>
          )}

          {tab === "timeline" && (
            <ol className="kw-timeline">
              {tl.map((e, i) => (
                <li key={i} className={`kw-tl-${e.type}`}>
                  <span className="kw-tl-type">{e.type.replace(/_/g, " ")}</span>
                  <span className="kw-tl-name">{e.name || e.rel_type || e.scope || ""}</span>
                  <span className="kw-tl-at">{e.at ? new Date(e.at).toLocaleString() : ""}</span>
                </li>
              ))}
              {tl.length === 0 && <li className="kw-muted">No knowledge events yet.</li>}
            </ol>
          )}

          {tab === "analytics" && an && (
            <div className="kw-analytics">
              <div className="kw-stat-row">
                <Stat label="Entities" v={an.entities} /><Stat label="Relationships" v={an.relationships} />
                <Stat label="Inferred" v={an.inferred_relationships} /><Stat label="Merged" v={an.merged_entities} />
                <Stat label="Density" v={an.density} /><Stat label="Agent contribs" v={an.growth.agent_contributions} />
              </div>
              <div className="kw-an-cols">
                <div>
                  <h4>Top connected</h4>
                  {an.top_connected.map((t) => (
                    <div className="kw-bar-row" key={t.id}>
                      <span className="kw-bar-label"><span className="kw-dot" style={{ background: entityColor(t.type) }} />{t.name}</span>
                      <span className="kw-bar"><span className="kw-bar-fill" style={{ width: `${Math.min(100, t.degree * 14)}px` }} /></span>
                      <span>{t.degree}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <h4>Entity types</h4>
                  {Object.entries(an.entity_types).map(([t, n]) => (
                    <div className="kw-bar-row" key={t}><span className="kw-bar-label"><span className="kw-dot" style={{ background: entityColor(t) }} />{t}</span><span>{n}</span></div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === "chat" && (
            <div className="kw-chat">
              <div className="kw-chat-log">
                {chat.length === 0 && <p className="kw-muted">Ask the graph: "How are React and Node.js related?" · "What depends on Virtual Memory?"</p>}
                {chat.map((m, i) => (
                  <div key={i} className={`kw-msg kw-msg-${m.role}`}>
                    {m.role === "assistant" ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown> : m.text}
                  </div>
                ))}
                {busy && <div className="kw-msg kw-msg-assistant kw-muted">thinking…</div>}
              </div>
              <div className="kw-chat-input">
                <input value={chatInput} placeholder="Ask the knowledge graph…" onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && sendChat()} />
                <button disabled={busy} onClick={sendChat}>Send</button>
              </div>
            </div>
          )}
        </main>

        {/* ---------- right: entity / relationship inspector ---------- */}
        <aside className="kw-right">
          {!entity && !rel && <div className="kw-empty">Click a node or edge to inspect it.</div>}

          {entity && (
            <div className="kw-detail">
              <h3><span className="kw-dot" style={{ background: entityColor(entity.entity_type) }} />{entity.canonical_name}</h3>
              <div className="kw-detail-meta">{entity.entity_type} · {Math.round(entity.confidence * 100)}% · deg {entity.degree} · v{entity.version}</div>
              {entity.aliases.length > 0 && <p><b>Aliases:</b> {entity.aliases.join(", ")}</p>}
              <p className="kw-muted">{entity.source_refs.length} source reference(s)</p>
              {entity.reasoning?.root_causes && entity.reasoning.root_causes.length > 0 && (
                <p><b>Depends ultimately on:</b> {entity.reasoning.root_causes.map((r) => r.entity).join(", ")}</p>
              )}
              <h4>Relationships ({entity.relationships.length})</h4>
              <ul className="kw-rels">
                {entity.relationships.map((r) => (
                  <li key={r.id} onClick={() => selectRel(r.id)}>
                    <b>{r.rel_type}</b> {r.source_id === entity.id ? `→ ${r.target_name}` : `← ${r.source_name}`}
                  </li>
                ))}
              </ul>
              <div className="kw-edit">
                <button onClick={() => { const n = prompt("Rename entity to:", entity.canonical_name); if (n) doEdit("rename_entity", { entity_id: entity.id, new_name: n }); }}>Rename</button>
                <button onClick={() => loadGraph(entity.id)}>Expand</button>
                <button className="kw-danger" onClick={() => { if (confirm(`Delete ${entity.canonical_name}?`)) doEdit("delete_entity", { entity_id: entity.id }); }}>Delete</button>
              </div>
            </div>
          )}

          {rel && (
            <div className="kw-detail">
              <h3>{rel.source.name} <span className="kw-rel-type">{rel.rel_type}</span> {rel.target.name}</h3>
              <div className="kw-detail-meta">
                {rel.directed ? "directed" : "undirected"} · weight {rel.weight.toFixed(2)} · {Math.round(rel.confidence * 100)}%
                {rel.inferred && <span className="kw-inferred-badge">AI-inferred</span>}
              </div>
              {rel.why_connected.length > 0 && (
                <><h4>Why connected</h4><ul className="kw-why">{rel.why_connected.map((p, i) => <li key={i}>{p.chain} <span className="kw-muted">{Math.round(p.path_confidence * 100)}%</span></li>)}</ul></>
              )}
              {rel.evidence.length > 0 && (
                <><h4>Evidence</h4>{rel.evidence.slice(0, 3).map((e, i) => <p key={i} className="kw-ev">{String((e as { text?: string; derivation?: string }).text || (e as { derivation?: string }).derivation || "")}</p>)}</>
              )}
              <div className="kw-edit">
                {rel.inferred && <button onClick={() => doEdit("approve_relationship", { rel_id: rel.id })}>Approve</button>}
                {rel.inferred && <button className="kw-danger" onClick={() => doEdit("reject_relationship", { rel_id: rel.id })}>Reject</button>}
                {!rel.inferred && <button className="kw-danger" onClick={() => { if (confirm("Delete relationship?")) doEdit("delete_relationship", { rel_id: rel.id }); }}>Delete</button>}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: number }) {
  return <div className="kw-stat"><span className="kw-stat-v">{v}</span><span className="kw-stat-l">{label}</span></div>;
}
