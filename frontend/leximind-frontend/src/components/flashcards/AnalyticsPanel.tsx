// Learning analytics: a row of stat tiles + a 30-day daily-activity bar chart (dependency-free,
// pure CSS bars). Rendered on the flashcards dashboard.

import type { LearningAnalytics } from "../../types";

export default function AnalyticsPanel({ a }: { a: LearningAnalytics }) {
  const maxDay = Math.max(1, ...a.daily_activity.map((d) => d.reviews));
  return (
    <div className="fc-analytics">
      <div className="fc-analytics-tiles">
        <Tile icon="🔥" value={`${a.study_streak_days}d`} label="Study streak" accent="#f97316" />
        <Tile icon="📅" value={a.due_today} label="Due today" accent="#0ea5e9" />
        <Tile icon="🆕" value={a.new_cards} label="New cards" accent="#6366f1" />
        <Tile icon="🎯" value={`${Math.round(a.accuracy * 100)}%`} label="Accuracy" accent="#10b981" />
        <Tile icon="🧠" value={`${Math.round(a.retention * 100)}%`} label="Retention" accent="#8b5cf6" />
        <Tile icon="🏆" value={a.mastered_cards} label="Mastered" accent="#eab308" />
        <Tile icon="⏱" value={`${(a.avg_response_time_ms / 1000).toFixed(1)}s`} label="Avg time" accent="#64748b" />
        <Tile icon="📚" value={a.reviews_total} label="Total reviews" accent="#14b8a6" />
      </div>

      <div className="fc-activity">
        <div className="fc-activity-head">
          <span>Daily activity</span>
          <span className="fc-activity-sub">{a.reviews_today} reviews today</span>
        </div>
        <div className="fc-activity-chart" role="img" aria-label="Daily review activity for the last 30 days">
          {a.daily_activity.map((d) => (
            <div key={d.date} className="fc-activity-bar-wrap" title={`${d.date}: ${d.reviews} reviews (${d.correct} correct)`}>
              <div className="fc-activity-bar" style={{ height: `${Math.round((d.reviews / maxDay) * 100)}%` }}>
                <div className="fc-activity-bar-correct" style={{ height: d.reviews ? `${Math.round((d.correct / d.reviews) * 100)}%` : "0%" }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Tile({ icon, value, label, accent }: { icon: string; value: string | number; label: string; accent: string }) {
  return (
    <div className="fc-tile" style={{ ["--accent" as string]: accent }}>
      <span className="fc-tile-icon" aria-hidden="true">{icon}</span>
      <span className="fc-tile-value">{value}</span>
      <span className="fc-tile-label">{label}</span>
    </div>
  );
}
