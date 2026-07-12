// A single temporal result rendered as a timestamp card: modality badge, timespan, speaker, content,
// optional on-screen frame preview, and a "jump to moment" action that opens the recording at the
// result's timestamp. Read-only presentation.

import { Link } from "react-router-dom";
import { fmtTime, MODALITY_META, type TemporalResult } from "../../api/temporal";
import { frameThumbnailUrl } from "../../api/media";

const SPK_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#a855f7"];
function speakerColor(label: string): string {
  const n = parseInt((label || "").replace(/\D/g, ""), 10) || 0;
  return SPK_COLORS[n % SPK_COLORS.length];
}

export default function TimestampCard({ ws, result }: { ws: string; result: TemporalResult }) {
  const meta = MODALITY_META[result.modality] || { icon: "•", color: "#64748b", label: result.modality };
  const jump = result.document_id
    ? `/workspace/${ws}/media?doc=${result.document_id}&t=${result.start_ms}`
    : `/workspace/${ws}/media`;
  const conf = Math.round((result.confidence || 0) * 100);
  return (
    <article className="tc">
      <div className="tc-rail" style={{ background: meta.color }} />
      <div className="tc-body">
        <header className="tc-head">
          <span className="tc-badge" style={{ color: meta.color, borderColor: meta.color }}>
            {meta.icon} {meta.label}
          </span>
          <span className="tc-time">⏱ {result.timespan}</span>
          {result.speaker_label && (
            <span className="tc-speaker" style={{ color: speakerColor(result.speaker_label) }}>
              🎙 {result.speaker_label}
            </span>
          )}
          <span className="tc-rank">#{result.final_rank}</span>
          <span className="tc-conf" title="confidence">{conf}%</span>
        </header>
        {result.title && result.title !== result.speaker_label && (
          <div className="tc-title">{result.title}</div>
        )}
        <p className="tc-content">{result.content}</p>
        <footer className="tc-foot">
          {result.frame_id && result.document_id && (
            <img
              className="tc-frame"
              src={frameThumbnailUrl(ws, result.document_id, result.frame_id)}
              alt={`frame at ${fmtTime(result.start_ms)}`}
              loading="lazy"
            />
          )}
          <Link className="tc-jump" to={jump}>▶ Jump to {fmtTime(result.start_ms)}</Link>
          {Array.isArray(result.metadata?.also_found_by) && (
            <span className="tc-also">also: {(result.metadata.also_found_by as string[]).join(", ")}</span>
          )}
        </footer>
      </div>
    </article>
  );
}
