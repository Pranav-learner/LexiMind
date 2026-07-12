// A compact timeline visualization of temporal results: each result is a dot placed on a shared time
// axis, colored by modality, sized by confidence. Hovering shows the moment; clicking selects it.

import { fmtTime, MODALITY_META, type TemporalResult } from "../../api/temporal";

export default function TimelineBar({
  results,
  onPick,
}: {
  results: TemporalResult[];
  onPick?: (r: TemporalResult) => void;
}) {
  if (!results.length) return null;
  const maxMs = Math.max(1, ...results.map((r) => r.end_ms));
  return (
    <div className="tl">
      <div className="tl-track">
        {results.map((r) => {
          const meta = MODALITY_META[r.modality] || { color: "#64748b", icon: "•", label: r.modality };
          const left = (r.start_ms / maxMs) * 100;
          const size = 8 + Math.round((r.confidence || 0) * 8);
          return (
            <button
              key={r.key}
              className="tl-dot"
              style={{ left: `${left}%`, background: meta.color, width: size, height: size }}
              title={`${meta.label} · ${r.timespan}${r.speaker_label ? " · " + r.speaker_label : ""}`}
              onClick={() => onPick?.(r)}
            />
          );
        })}
      </div>
      <div className="tl-axis">
        <span>0:00</span>
        <span>{fmtTime(maxMs / 2)}</span>
        <span>{fmtTime(maxMs)}</span>
      </div>
    </div>
  );
}
