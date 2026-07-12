// Live processing dashboard for a media job: the ordered temporal pipeline stages, a progress bar,
// per-stage state, elapsed/estimate, error surface + retry/cancel. Purely presentational — the
// parent owns polling and passes the latest job in.

import type { MediaJob } from "../../api/media";

// The temporal pipeline, in order. Audio jobs skip the video-only stages (greyed out).
const STAGES: { key: string; label: string; videoOnly?: boolean }[] = [
  { key: "validating", label: "Validation" },
  { key: "transcription", label: "Speech-to-Text" },
  { key: "diarization", label: "Speaker Diarization" },
  { key: "scene_detection", label: "Scene Detection", videoOnly: true },
  { key: "frame_extraction", label: "Frame Extraction", videoOnly: true },
  { key: "subtitles", label: "Subtitles", videoOnly: true },
  { key: "chunking", label: "Temporal Chunking" },
  { key: "completed", label: "Ready" },
];

function stageState(job: MediaJob, key: string): "done" | "active" | "pending" | "skipped" {
  const order = STAGES.map((s) => s.key);
  const cur = order.indexOf(job.stage);
  const idx = order.indexOf(key);
  if (job.status === "completed") return "done";
  if (job.media_kind === "audio" && STAGES[idx]?.videoOnly) return "skipped";
  if (cur < 0) return "pending";
  if (idx < cur) return "done";
  if (idx === cur) return "active";
  return "pending";
}

export default function MediaProgress({
  job,
  onRetry,
  onCancel,
}: {
  job: MediaJob;
  onRetry?: () => void;
  onCancel?: () => void;
}) {
  const failed = job.status === "failed";
  const cancelled = job.status === "cancelled";
  const active = job.status === "queued" || job.status === "processing";

  return (
    <div className={`media-progress media-progress--${job.status}`}>
      <div className="media-progress-head">
        <span className={`media-badge media-badge--${job.status}`}>{job.status}</span>
        <span className="media-progress-stage">{job.stage.replace(/_/g, " ")}</span>
        <span className="media-progress-pct">{job.progress}%</span>
      </div>

      <div className="media-bar">
        <div className="media-bar-fill" style={{ width: `${job.progress}%` }} />
      </div>

      <ol className="media-stages">
        {STAGES.map((s) => {
          const st = stageState(job, s.key);
          return (
            <li key={s.key} className={`media-stage media-stage--${st}`}>
              <span className="media-stage-dot" />
              <span className="media-stage-label">{s.label}</span>
              {st === "skipped" && <span className="media-stage-note">n/a</span>}
            </li>
          );
        })}
      </ol>

      {failed && (
        <div className="media-error">
          <strong>Processing failed.</strong> {job.error}
          {onRetry && (
            <button className="media-btn" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
      {cancelled && onRetry && (
        <div className="media-error media-error--muted">
          Cancelled. <button className="media-btn" onClick={onRetry}>Retry</button>
        </div>
      )}
      {active && onCancel && (
        <button className="media-btn media-btn--ghost" onClick={onCancel}>
          Cancel processing
        </button>
      )}
    </div>
  );
}
