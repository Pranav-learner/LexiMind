// The Knowledge Dashboard — the analytics home of every workspace. Route:
//   /workspace/:workspaceId/dashboard
//
// Unifies knowledge stats, AI usage, learning analytics, retrieval config, an activity heatmap +
// charts, AI-generated insights, an activity timeline, and quick actions into one responsive grid.
// Everything comes from the cached /dashboard endpoint (one round-trip); a Refresh busts the cache.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as analytics from "../api/analytics";
import { ApiError } from "../api/client";
import { DonutChart, Heatmap, LineChart } from "../components/dashboard/Charts";
import type { DashboardOverview, DashChartSeries } from "../types";

function human(bytes: number): string {
  if (!bytes) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

function relTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export default function Dashboard() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [activityFilter, setActivityFilter] = useState<string>("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setError(null);
    try {
      setData(await analytics.getDashboard(workspaceId, signal));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load dashboard.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function refresh() {
    setRefreshing(true);
    try { setData(await analytics.refreshDashboard(workspaceId)); } catch { /* ignore */ }
    finally { setRefreshing(false); }
  }

  const series = useMemo(() => {
    const map = new Map<string, DashChartSeries>();
    data?.charts.series.forEach((s) => map.set(s.key, s));
    return map;
  }, [data]);

  const filteredActivity = useMemo(() => {
    const items = data?.activity.items || [];
    return activityFilter ? items.filter((e) => e.type === activityFilter) : items;
  }, [data, activityFilter]);

  if (loading) {
    return <div className="ws-page dash-page"><div className="dash-loading"><span className="ws-brand-mark spin">🧠</span><p>Loading dashboard…</p></div></div>;
  }
  if (error || !data) {
    return (
      <div className="ws-page dash-page"><div className="ws-page-body">
        <div className="ws-error-banner">{error || "No data."}</div>
        <Link className="ws-link" to={`/workspace/${workspaceId}`}>← Back to workspace</Link>
      </div></div>
    );
  }

  const { knowledge: k, ai_usage: ai, learning: l, retrieval: r, insights } = data;
  const activityTypes = Array.from(new Set((data.activity.items || []).map((e) => e.type)));

  return (
    <div className="ws-page dash-page">
      <header className="ws-header">
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {k.workspace_name}</Link>
        <div className="ws-header-right">
          <button className="ws-btn ghost" onClick={refresh} disabled={refreshing}>{refreshing ? "Refreshing…" : "↻ Refresh"}</button>
        </div>
      </header>

      <div className="dash-body">
        <div className="ws-page-title">
          <div><h1>📊 Knowledge Dashboard</h1><p>Your knowledge base at a glance</p></div>
        </div>

        {/* quick actions */}
        <div className="dash-quick">
          <QuickAction to={`/workspace/${workspaceId}/library`} icon="📚" label="Library" />
          <QuickAction to={`/workspace/${workspaceId}/chat`} icon="💬" label="Ask AI" />
          <QuickAction to={`/workspace/${workspaceId}/summaries`} icon="📄" label="Summarize" />
          <QuickAction to={`/workspace/${workspaceId}/notes`} icon="📝" label="Notes" />
          <QuickAction to={`/workspace/${workspaceId}/flashcards`} icon="🎴" label="Flashcards" />
          <QuickAction to={`/workspace/${workspaceId}/flashcards/review`} icon="🎓" label={l.due_today + l.new_cards > 0 ? `Study ${l.due_today + l.new_cards}` : "Study"} highlight={l.due_today + l.new_cards > 0} />
          <QuickAction to={`/workspace/${workspaceId}/knowledge`} icon="🔎" label="Explore" />
        </div>

        {/* overview cards */}
        <div className="dash-cards">
          <StatCard icon="📄" value={k.documents} label="Documents" sub={`${k.pages} pages`} accent="#6366f1" />
          <StatCard icon="🧩" value={k.chunks} label="Chunks" sub={`${human(k.storage_bytes)}`} accent="#0ea5e9" />
          <StatCard icon="💬" value={ai.questions_asked} label="Questions" sub={`${ai.conversations} chats`} accent="#8b5cf6" />
          <StatCard icon="📝" value={ai.notes_generated} label="Notes" sub={`${ai.summaries_generated} summaries`} accent="#14b8a6" />
          <StatCard icon="🎴" value={ai.flashcards_generated} label="Flashcards" sub={`${l.mastered_cards} mastered`} accent="#f59e0b" />
          <StatCard icon="🔥" value={`${l.study_streak_days}d`} label="Streak" sub={`${l.reviews_today} today`} accent="#f97316" />
          <StatCard icon="🎯" value={`${Math.round(l.accuracy * 100)}%`} label="Accuracy" sub={`${Math.round(l.retention * 100)}% retention`} accent="#10b981" />
          <StatCard icon="🔗" value={ai.citation_usage} label="Citations" sub="traceable" accent="#ec4899" />
        </div>

        {/* insights */}
        {insights.length > 0 && (
          <section className="dash-section">
            <h2 className="dash-h2">💡 Insights & Recommendations</h2>
            <div className="dash-insights">
              {insights.map((i) => (
                <div key={i.id} className={`dash-insight sev-${i.severity}`}>
                  <span className="dash-insight-icon" aria-hidden="true">{i.icon}</span>
                  <div className="dash-insight-body">
                    <strong>{i.title}</strong>
                    <p>{i.message}</p>
                  </div>
                  {i.action_route && (
                    <button className="ws-btn ghost dash-insight-action" onClick={() => navigate(i.action_route!)}>{i.action_label || "Open"}</button>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* charts */}
        <section className="dash-section">
          <h2 className="dash-h2">📈 Activity & Growth</h2>
          <div className="dash-charts">
            {series.get("daily_activity") && (
              <ChartCard title="Activity heatmap (30 days)" wide>
                <Heatmap points={series.get("daily_activity")!.points} label="Daily activity" />
              </ChartCard>
            )}
            {series.get("activity_line") && (
              <ChartCard title="Daily activity">
                <LineChart points={series.get("activity_line")!.points} color="#6366f1" label="Activity" />
              </ChartCard>
            )}
            {series.get("ai_usage") && (
              <ChartCard title="AI messages">
                <LineChart points={series.get("ai_usage")!.points} color="#8b5cf6" label="AI usage" />
              </ChartCard>
            )}
            {series.get("knowledge_growth") && (
              <ChartCard title="Knowledge growth">
                <LineChart points={series.get("knowledge_growth")!.points} color="#10b981" label="Documents over time" />
              </ChartCard>
            )}
            {series.get("asset_distribution") && (
              <ChartCard title="Workspace distribution">
                <DonutChart points={series.get("asset_distribution")!.points} />
              </ChartCard>
            )}
            {series.get("flashcard_progress") && (
              <ChartCard title="Flashcard progress">
                <DonutChart points={series.get("flashcard_progress")!.points} />
              </ChartCard>
            )}
          </div>
        </section>

        {/* AI usage + retrieval detail */}
        <section className="dash-section dash-two-col">
          <div className="dash-panel">
            <h3 className="dash-h3">⚡ AI Usage</h3>
            <MetricRow label="Avg response time" value={`${(ai.avg_response_time_ms / 1000).toFixed(1)}s`} />
            <MetricRow label="Avg retrieval time" value={`${ai.avg_retrieval_ms}ms`} />
            <MetricRow label="Avg context size" value={`${ai.avg_context_size} tok`} />
            <MetricRow label="Avg tokens / answer" value={ai.avg_token_usage} />
            <MetricRow label="Total tokens" value={ai.total_tokens.toLocaleString()} />
            <MetricRow label="Est. cost" value={`$${ai.estimated_cost_usd.toFixed(2)}`} hint="local model" />
            {ai.model_usage.length > 0 && (
              <div className="dash-chips">{ai.model_usage.map((m) => <span key={m.model} className="dash-chip">{m.model} · {m.count}</span>)}</div>
            )}
          </div>

          <div className="dash-panel">
            <h3 className="dash-h3">🔬 Retrieval & Context Engine</h3>
            <div className="dash-chips">
              <span className={`dash-chip ${r.dense_enabled ? "on" : ""}`}>Dense</span>
              <span className={`dash-chip ${r.bm25_enabled ? "on" : ""}`}>BM25</span>
              <span className={`dash-chip ${r.rrf_enabled ? "on" : ""}`}>RRF k={r.rrf_k}</span>
              <span className={`dash-chip ${r.reranker_enabled ? "on" : ""}`}>Reranker</span>
              <span className={`dash-chip ${r.compression_enabled ? "on" : ""}`}>Compression</span>
            </div>
            <MetricRow label="Top-K (final)" value={r.final_top_k} />
            <MetricRow label="Context window" value={`${r.context_window} tok`} />
            <MetricRow label="Context utilization" value={`${Math.round(r.context_utilization * 100)}%`} />
            <MetricRow label="Embedding model" value={r.embedding_model} />
            <MetricRow label="Index health" value={k.index_health} />
            <p className="dash-note">{r.note}</p>
          </div>
        </section>

        {/* activity timeline */}
        <section className="dash-section">
          <div className="dash-timeline-head">
            <h2 className="dash-h2">🕑 Recent Activity</h2>
            <select value={activityFilter} onChange={(e) => setActivityFilter(e.target.value)} aria-label="Filter activity">
              <option value="">All</option>
              {activityTypes.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {filteredActivity.length === 0 ? (
            <p className="dash-note">No activity yet.</p>
          ) : (
            <ul className="dash-timeline">
              {filteredActivity.map((e, i) => (
                <li key={i} className="dash-timeline-item" onClick={() => e.route && navigate(e.route)} role={e.route ? "button" : undefined} tabIndex={e.route ? 0 : undefined}
                    onKeyDown={(ev) => { if (ev.key === "Enter" && e.route) navigate(e.route); }}>
                  <span className="dash-timeline-icon">{e.icon}</span>
                  <span className="dash-timeline-title">{e.title}</span>
                  <span className="dash-timeline-time">{relTime(e.timestamp)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function QuickAction({ to, icon, label, highlight }: { to: string; icon: string; label: string; highlight?: boolean }) {
  return (
    <Link className={`dash-quick-action${highlight ? " highlight" : ""}`} to={to}>
      <span className="dash-quick-icon" aria-hidden="true">{icon}</span>
      <span>{label}</span>
    </Link>
  );
}

function StatCard({ icon, value, label, sub, accent }: { icon: string; value: number | string; label: string; sub?: string; accent: string }) {
  return (
    <div className="dash-stat-card" style={{ ["--accent" as string]: accent }}>
      <span className="dash-stat-icon" aria-hidden="true">{icon}</span>
      <span className="dash-stat-value">{value}</span>
      <span className="dash-stat-label">{label}</span>
      {sub && <span className="dash-stat-sub">{sub}</span>}
    </div>
  );
}

function ChartCard({ title, children, wide }: { title: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`dash-chart-card${wide ? " wide" : ""}`}>
      <h4 className="dash-chart-title">{title}</h4>
      {children}
    </div>
  );
}

function MetricRow({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="dash-metric-row">
      <span className="dash-metric-label">{label}{hint && <em className="dash-metric-hint"> · {hint}</em>}</span>
      <span className="dash-metric-value">{value}</span>
    </div>
  );
}
