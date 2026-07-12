// Interactive, lane-based timeline synchronized with playback. Each lane (chapters/topics/events/
// speakers/scenes) renders its items as clickable segments on a shared time axis; a playhead tracks
// the current position. Clicking a segment seeks the player.

import { fmtTime, LANE_META, type Timeline, type TimelineItem } from "../../api/mediaworkspace";

export default function TimelineLanes({
  timeline,
  positionMs,
  onSeek,
}: {
  timeline: Timeline;
  positionMs: number;
  onSeek: (ms: number, item?: TimelineItem) => void;
}) {
  const dur = Math.max(1, timeline.duration_ms);
  const playheadPct = Math.min(100, (positionMs / dur) * 100);

  return (
    <div className="tll">
      <div className="tll-lanes">
        {timeline.lanes.map((lane) => {
          const meta = LANE_META[lane] || { icon: "•", color: "#64748b", label: lane };
          const items = timeline.items.filter((i) => i.lane === lane);
          return (
            <div key={lane} className="tll-lane">
              <div className="tll-lane-label" style={{ color: meta.color }}>{meta.icon} {meta.label}</div>
              <div className="tll-track">
                {items.map((i) => {
                  const left = (i.start_ms / dur) * 100;
                  const width = Math.max(0.8, ((i.end_ms - i.start_ms) / dur) * 100);
                  const active = positionMs >= i.start_ms && positionMs < i.end_ms;
                  return (
                    <button
                      key={i.id}
                      className={`tll-seg ${active ? "is-active" : ""}`}
                      style={{ left: `${left}%`, width: `${width}%`, background: meta.color }}
                      title={`${i.title} · ${i.timespan}`}
                      onClick={() => onSeek(i.start_ms, i)}
                    >
                      <span className="tll-seg-label">{i.title}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className="tll-playhead" style={{ left: `${playheadPct}%` }} />
      </div>
      <div className="tll-axis">
        <span>0:00</span><span>{fmtTime(dur / 2)}</span><span>{fmtTime(dur)}</span>
      </div>
    </div>
  );
}
