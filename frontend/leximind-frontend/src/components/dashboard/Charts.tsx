// Dependency-free, theme-aware SVG charts for the Knowledge Dashboard (Phase 3, Module 9).
//
// EDITOR NOTE: LexiMind deliberately avoids a heavyweight charting dependency (consistent with the
// markdown-editor / CSS-chart decisions in earlier modules) — these components are small, responsive
// (viewBox-scaled), accessible (role/aria + <title> tooltips), and inherit the app's CSS variables
// so they look right in light and dark. LineChart, Bar-less DonutChart, and a GitHub-style Heatmap
// cover every dashboard series; a real charting lib can replace them later behind the same props.

import type { ChartPoint } from "../../types";

const PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#f97316"];

// ---------------------------------------------------------------- LineChart
export function LineChart({ points, color = "#6366f1", height = 120, label }: {
  points: ChartPoint[];
  color?: string;
  height?: number;
  label?: string;
}) {
  const values = points.map((p) => p.value ?? 0);
  const max = Math.max(1, ...values);
  const W = 300;
  const H = 100;
  const n = points.length;
  const step = n > 1 ? W / (n - 1) : W;
  const coords = points.map((p, i) => [i * step, H - ((p.value ?? 0) / max) * (H - 8) - 4]);
  const linePath = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${W},${H} L0,${H} Z`;
  const gid = `grad-${(label || color).replace(/\W/g, "")}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} preserveAspectRatio="none"
         role="img" aria-label={label || "Line chart"} className="dash-linechart">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gid})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {coords.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="3" fill={color} className="dash-line-dot">
          <title>{points[i].date}: {points[i].value}</title>
        </circle>
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------- DonutChart
export function DonutChart({ points, size = 140 }: { points: ChartPoint[]; size?: number }) {
  const total = points.reduce((s, p) => s + (p.value ?? 0), 0);
  const r = 60;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="dash-donut">
      <svg viewBox="0 0 160 160" width={size} height={size} role="img" aria-label="Distribution">
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--surface-2)" strokeWidth="18" />
        {total > 0 && points.map((p, i) => {
          const frac = (p.value ?? 0) / total;
          const seg = frac * c;
          const el = (
            <circle key={i} cx="80" cy="80" r={r} fill="none"
                    stroke={PALETTE[i % PALETTE.length]} strokeWidth="18"
                    strokeDasharray={`${seg} ${c - seg}`} strokeDashoffset={-offset}
                    transform="rotate(-90 80 80)" strokeLinecap="butt">
              <title>{p.label}: {p.value} ({Math.round(frac * 100)}%)</title>
            </circle>
          );
          offset += seg;
          return el;
        })}
        <text x="80" y="76" textAnchor="middle" className="dash-donut-total">{total}</text>
        <text x="80" y="94" textAnchor="middle" className="dash-donut-sub">total</text>
      </svg>
      <div className="dash-donut-legend">
        {points.map((p, i) => (
          <div key={i} className="dash-legend-item">
            <span className="dash-legend-dot" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="dash-legend-label">{p.label}</span>
            <span className="dash-legend-value">{p.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Heatmap (GitHub-style)
export function Heatmap({ points, label }: { points: ChartPoint[]; label?: string }) {
  const max = Math.max(1, ...points.map((p) => p.value ?? 0));
  const level = (v: number) => (v <= 0 ? 0 : v >= max * 0.75 ? 4 : v >= max * 0.5 ? 3 : v >= max * 0.25 ? 2 : 1);
  // Chunk into weeks (columns) of 7 (rows). Pad the front so the grid aligns to weeks.
  const cells = points.map((p) => ({ ...p, lvl: level(p.value ?? 0) }));
  const weeks: typeof cells[] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return (
    <div className="dash-heatmap" role="img" aria-label={label || "Activity heatmap"}>
      {weeks.map((week, wi) => (
        <div key={wi} className="dash-heatmap-col">
          {week.map((cell, ci) => (
            <span key={ci} className={`dash-heatmap-cell lvl-${cell.lvl}`} title={`${cell.date}: ${cell.value} activities`} />
          ))}
        </div>
      ))}
      <div className="dash-heatmap-legend">
        <span>Less</span>
        {[0, 1, 2, 3, 4].map((l) => <span key={l} className={`dash-heatmap-cell lvl-${l}`} />)}
        <span>More</span>
      </div>
    </div>
  );
}
