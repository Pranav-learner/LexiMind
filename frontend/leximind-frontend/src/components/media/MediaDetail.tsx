// Tabbed detail view for a processed recording: Transcript, Speakers, Scenes & Frames, Subtitles,
// Temporal Chunks, and Metadata. Each tab lazily loads its slice from the media API. Read-only —
// this module is the ingestion layer; retrieval/chat over media arrive in a later module.

import { useEffect, useState } from "react";
import {
  fmtTime,
  frameThumbnailUrl,
  getMediaChunks,
  getMetadata,
  getScenes,
  getFrames,
  getSpeakers,
  getSubtitles,
  getTranscript,
  type MediaChunk,
  type MediaFrame,
  type MediaMetadata,
  type Scene,
  type SpeakerTimeline,
  type Subtitle,
  type TranscriptResponse,
} from "../../api/media";

type Tab = "transcript" | "speakers" | "scenes" | "subtitles" | "chunks" | "metadata";
const TABS: { key: Tab; label: string }[] = [
  { key: "transcript", label: "Transcript" },
  { key: "speakers", label: "Speakers" },
  { key: "scenes", label: "Scenes & Frames" },
  { key: "subtitles", label: "Subtitles" },
  { key: "chunks", label: "Temporal Chunks" },
  { key: "metadata", label: "Metadata" },
];

const SPK_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#a855f7"];
function speakerColor(label: string): string {
  const n = parseInt(label.replace(/\D/g, ""), 10) || 0;
  return SPK_COLORS[n % SPK_COLORS.length];
}

export default function MediaDetail({ ws, docId }: { ws: string; docId: string }) {
  const [tab, setTab] = useState<Tab>("transcript");
  return (
    <div className="media-detail">
      <nav className="media-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`media-tab ${tab === t.key ? "is-active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <div className="media-tab-body">
        {tab === "transcript" && <TranscriptTab ws={ws} docId={docId} />}
        {tab === "speakers" && <SpeakersTab ws={ws} docId={docId} />}
        {tab === "scenes" && <ScenesTab ws={ws} docId={docId} />}
        {tab === "subtitles" && <SubtitlesTab ws={ws} docId={docId} />}
        {tab === "chunks" && <ChunksTab ws={ws} docId={docId} />}
        {tab === "metadata" && <MetadataTab ws={ws} docId={docId} />}
      </div>
    </div>
  );
}

function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    setErr(null);
    fn(ctrl.signal)
      .then(setData)
      .catch((e) => { if (e?.name !== "AbortError") setErr(String(e?.message || e)); });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, err };
}

function TranscriptTab({ ws, docId }: { ws: string; docId: string }) {
  const { data, err } = useAsync<TranscriptResponse>((s) => getTranscript(ws, docId, undefined, s), [ws, docId]);
  if (err) return <p className="media-empty">{err}</p>;
  if (!data) return <p className="media-empty">Loading transcript…</p>;
  if (!data.segments.length) return <p className="media-empty">No transcript segments.</p>;
  return (
    <div className="media-transcript">
      {data.segments.map((seg) => (
        <div key={seg.id} className="media-seg">
          <span className="media-seg-time">{fmtTime(seg.start_ms)}</span>
          <span className="media-seg-spk" style={{ color: speakerColor(seg.speaker_label) }}>
            {seg.speaker_label || "—"}
          </span>
          <span className="media-seg-text">{seg.text}</span>
        </div>
      ))}
    </div>
  );
}

function SpeakersTab({ ws, docId }: { ws: string; docId: string }) {
  const { data, err } = useAsync<SpeakerTimeline>((s) => getSpeakers(ws, docId, s), [ws, docId]);
  if (err) return <p className="media-empty">{err}</p>;
  if (!data) return <p className="media-empty">Loading speakers…</p>;
  const total = Math.max(1, ...data.timeline.map((t) => t.end_ms));
  return (
    <div className="media-speakers">
      <div className="media-speaker-cards">
        {data.speakers.map((sp) => (
          <div key={sp.id} className="media-speaker-card">
            <span className="media-speaker-swatch" style={{ background: speakerColor(sp.speaker_label) }} />
            <div>
              <div className="media-speaker-name">{sp.display_name || sp.speaker_label}</div>
              <div className="media-speaker-meta">
                {Math.round(sp.total_speaking_ms / 1000)}s · {sp.turn_count} turns · {sp.segment_count} segments
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="media-timeline">
        {data.timeline.map((t, i) => (
          <div
            key={i}
            className="media-timeline-turn"
            title={`${t.speaker_label}: ${fmtTime(t.start_ms)}–${fmtTime(t.end_ms)}`}
            style={{
              left: `${(t.start_ms / total) * 100}%`,
              width: `${Math.max(0.5, ((t.end_ms - t.start_ms) / total) * 100)}%`,
              background: speakerColor(t.speaker_label),
            }}
          />
        ))}
      </div>
    </div>
  );
}

function ScenesTab({ ws, docId }: { ws: string; docId: string }) {
  const scenes = useAsync<Scene[]>((s) => getScenes(ws, docId, s), [ws, docId]);
  const frames = useAsync<MediaFrame[]>((s) => getFrames(ws, docId, undefined, s), [ws, docId]);
  if (scenes.err) return <p className="media-empty">{scenes.err}</p>;
  if (!scenes.data || !frames.data) return <p className="media-empty">Loading scenes…</p>;
  if (!frames.data.length) return <p className="media-empty">No frames (audio-only recording).</p>;
  return (
    <div className="media-scenes">
      <p className="media-subhead">{scenes.data.length} scenes · {frames.data.length} frames</p>
      <div className="media-frame-grid">
        {frames.data.map((f) => (
          <figure key={f.id} className="media-frame">
            <img src={frameThumbnailUrl(ws, docId, f.id)} alt={`frame at ${fmtTime(f.timestamp_ms)}`} loading="lazy" />
            <figcaption>
              <span>{fmtTime(f.timestamp_ms)}</span>
              {f.ocr_text ? <span className="media-frame-ocr" title={f.ocr_text}>📝</span> : null}
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

function SubtitlesTab({ ws, docId }: { ws: string; docId: string }) {
  const { data, err } = useAsync<Subtitle[]>((s) => getSubtitles(ws, docId, s), [ws, docId]);
  if (err) return <p className="media-empty">{err}</p>;
  if (!data) return <p className="media-empty">Loading subtitles…</p>;
  if (!data.length) return <p className="media-empty">No embedded subtitles.</p>;
  return (
    <div className="media-transcript">
      {data.map((sub) => (
        <div key={sub.id} className="media-seg">
          <span className="media-seg-time">{fmtTime(sub.start_ms)}</span>
          <span className="media-seg-src">{sub.source}</span>
          <span className="media-seg-text">{sub.text}</span>
        </div>
      ))}
    </div>
  );
}

function ChunksTab({ ws, docId }: { ws: string; docId: string }) {
  const [type, setType] = useState<string>("");
  const { data, err } = useAsync<MediaChunk[]>((s) => getMediaChunks(ws, docId, type || undefined, s), [ws, docId, type]);
  const TYPES = ["", "transcript", "speaker", "scene", "subtitle", "ocr", "frame"];
  return (
    <div className="media-chunks">
      <div className="media-chunk-filter">
        {TYPES.map((t) => (
          <button key={t || "all"} className={`media-chip ${type === t ? "is-active" : ""}`} onClick={() => setType(t)}>
            {t || "all"}
          </button>
        ))}
      </div>
      {err && <p className="media-empty">{err}</p>}
      {!data ? (
        <p className="media-empty">Loading chunks…</p>
      ) : (
        <ul className="media-chunk-list">
          {data.map((c) => (
            <li key={c.id} className="media-chunk">
              <span className={`media-chunk-type media-chunk-type--${c.chunk_type}`}>{c.chunk_type}</span>
              <span className="media-chunk-time">{fmtTime(c.start_ms)}–{fmtTime(c.end_ms)}</span>
              <span className="media-chunk-content">{c.content}</span>
              <span className="media-chunk-embed" title="future embedding queue">{c.embedding_status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MetadataTab({ ws, docId }: { ws: string; docId: string }) {
  const { data, err } = useAsync<MediaMetadata>((s) => getMetadata(ws, docId, s), [ws, docId]);
  if (err) return <p className="media-empty">{err}</p>;
  if (!data) return <p className="media-empty">Loading metadata…</p>;
  const rows: [string, string][] = [
    ["Kind", data.media_kind],
    ["Category", data.media_category],
    ["Language", data.language || "—"],
    ["Duration", data.duration_readable],
    ["Speakers", String(data.speaker_count)],
    ["Scenes", String(data.scene_count)],
    ["Frames", String(data.frame_count)],
    ["Subtitles", String(data.subtitle_count)],
    ["Transcript segments", String(data.segment_count)],
    ["OCR frames", String(data.ocr_frame_count)],
    ["Temporal chunks", String(data.chunk_count)],
    ["Words", String(data.word_count)],
    ["Avg speech rate", data.avg_speech_rate ? `${data.avg_speech_rate} wpm` : "—"],
    ["Container", data.container || "—"],
    ["Video codec", data.video?.codec || "—"],
    ["Audio codec", data.audio.codec || "—"],
    ["Processing time", `${data.processing_ms} ms`],
    ["Cache hits", String(data.cache_hits)],
    ["Pipeline", data.pipeline_version],
  ];
  return (
    <table className="media-meta">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th>{k}</th>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
