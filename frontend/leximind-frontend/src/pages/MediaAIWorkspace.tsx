// Audio & Video AI Workspace (Phase 5, Module 4) — the unified capstone. Route:
//   /workspace/:workspaceId/media-ai   (optionally ?doc=…)
//
// One screen where recordings behave like documents: a media library, a synchronized player, an
// interactive multi-lane timeline, a live transcript, a temporal-grounded AI chat whose citations
// seek the player, and an AI action panel that generates knowledge assets. All intelligence flows
// through the existing backend services (temporal retrieval → prompt → answer service); this page is
// pure orchestration + UX. Nothing here re-implements retrieval, chat, or generation.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getTranscript, type TranscriptSegment } from "../api/media";
import {
  AI_ACTIONS,
  fetchMediaUrl,
  fmtTime,
  getLibrary,
  getPlayback,
  getTimeline,
  mediaChat,
  recordInteraction,
  runAction,
  type LibraryItem,
  type MediaChatResponse,
  type PlaybackMeta,
  type Timeline,
  type TimelineItem,
} from "../api/mediaworkspace";
import TimelineLanes from "../components/mediaai/TimelineLanes";
import "../styles/mediaai.css";

interface ChatTurn { role: "user" | "assistant"; content: string; citations?: MediaChatResponse["citations"]; grounded?: boolean; }

export default function MediaAIWorkspace() {
  const { workspaceId = "" } = useParams();
  const [params] = useSearchParams();
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [docId, setDocId] = useState<string | null>(params.get("doc"));
  const [playback, setPlayback] = useState<PlaybackMeta | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [positionMs, setPositionMs] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const mediaRef = useRef<HTMLVideoElement | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  // --- load library ---
  useEffect(() => {
    getLibrary(workspaceId)
      .then((r) => { setLibrary(r.items); setDocId((cur) => cur ?? r.items[0]?.document_id ?? null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load media library."));
  }, [workspaceId]);

  // --- load the selected recording (playback meta + timeline + transcript + media blob) ---
  useEffect(() => {
    if (!docId) return;
    const ctrl = new AbortController();
    setPlayback(null); setTimeline(null); setSegments([]); setPositionMs(0);
    setMediaUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return null; });
    (async () => {
      try {
        const [pb, tl, tr] = await Promise.all([
          getPlayback(workspaceId, docId, ctrl.signal),
          getTimeline(workspaceId, docId, ctrl.signal),
          getTranscript(workspaceId, docId, undefined, ctrl.signal),
        ]);
        setPlayback(pb); setTimeline(tl); setSegments(tr.segments);
        try { setMediaUrl(await fetchMediaUrl(workspaceId, docId)); } catch { /* media file optional in some states */ }
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e instanceof ApiError ? e.message : "Failed to load recording.");
      }
    })();
    return () => ctrl.abort();
  }, [workspaceId, docId]);

  const seek = useCallback((ms: number, item?: TimelineItem) => {
    const el = mediaRef.current;
    if (el) { el.currentTime = ms / 1000; el.play().catch(() => undefined); }
    setPositionMs(ms);
    if (docId) recordInteraction(workspaceId, { event_type: item ? "timeline_click" : "seek", document_id: docId, position_ms: ms, target: item?.id });
  }, [workspaceId, docId]);

  const activeSegIdx = useMemo(
    () => segments.findIndex((s) => positionMs >= s.start_ms && positionMs < s.end_ms),
    [segments, positionMs],
  );

  // auto-scroll transcript to the active line
  useEffect(() => {
    if (activeSegIdx < 0 || !transcriptRef.current) return;
    const node = transcriptRef.current.querySelector<HTMLElement>(`[data-seg="${activeSegIdx}"]`);
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeSegIdx]);

  const doAction = async (action: string) => {
    if (!docId) return;
    try {
      const res = await runAction(workspaceId, { action, document_id: docId, count: 10 });
      setToast(`Generating ${res.asset_type}… (${res.status})`);
    } catch (e) {
      setToast(e instanceof ApiError ? e.message : "Action failed.");
    }
  };

  const selected = library.find((d) => d.document_id === docId);

  return (
    <div className="mai-page">
      <header className="mai-header">
        <div>
          <Link to={`/workspace/${workspaceId}`} className="mai-back">← Workspace</Link>
          <h1>🎧 Audio &amp; Video AI Workspace</h1>
        </div>
        {toast && <div className="mai-toast" onClick={() => setToast(null)}>{toast}</div>}
      </header>
      {error && <div className="mai-banner">{error}</div>}

      <div className="mai-grid">
        {/* library */}
        <aside className="mai-library">
          <h2>Recordings</h2>
          {!library.length && <p className="mai-empty">No recordings yet. <Link to={`/workspace/${workspaceId}/media`}>Upload one →</Link></p>}
          <ul>
            {library.map((d) => (
              <li key={d.document_id}>
                <button className={`mai-lib ${docId === d.document_id ? "is-active" : ""}`} onClick={() => setDocId(d.document_id)}>
                  <span>{d.media_kind === "audio" ? "🎧" : "🎬"}</span>
                  <span className="mai-lib-name" title={d.display_name}>{d.display_name}</span>
                  {d.intelligence_ready && <span className="mai-lib-ready" title="temporal intelligence ready">✨</span>}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        {/* center: player + timeline + transcript */}
        <main className="mai-main">
          {!docId && <p className="mai-empty">Select a recording.</p>}
          {docId && (
            <>
              <div className="mai-player-wrap">
                {mediaUrl ? (
                  playback?.media_kind === "audio" ? (
                    <audio ref={mediaRef as React.RefObject<HTMLAudioElement>} src={mediaUrl} controls
                      onTimeUpdate={(e) => setPositionMs(Math.round(e.currentTarget.currentTime * 1000))}
                      onPlay={() => docId && recordInteraction(workspaceId, { event_type: "playback", document_id: docId, position_ms: positionMs })}
                      style={{ width: "100%" }} />
                  ) : (
                    <video ref={mediaRef} src={mediaUrl} controls
                      onTimeUpdate={(e) => setPositionMs(Math.round(e.currentTarget.currentTime * 1000))}
                      onPlay={() => docId && recordInteraction(workspaceId, { event_type: "playback", document_id: docId, position_ms: positionMs })}
                      className="mai-video" />
                  )
                ) : (
                  <div className="mai-noplayer">
                    <span>{selected?.media_kind === "audio" ? "🎧" : "🎬"}</span>
                    <p>{selected?.display_name}</p>
                    <small>{playback ? fmtTime(playback.duration_ms) : ""} · position {fmtTime(positionMs)}</small>
                  </div>
                )}
                <div className="mai-pos">▶ {fmtTime(positionMs)} {playback && <>/ {fmtTime(playback.duration_ms)}</>}</div>
              </div>

              {timeline && timeline.items.length > 0 && (
                <section className="mai-timeline">
                  <h3>Interactive timeline</h3>
                  <TimelineLanes timeline={timeline} positionMs={positionMs} onSeek={seek} />
                </section>
              )}

              <section className="mai-transcript" ref={transcriptRef}>
                <h3>Transcript</h3>
                {!segments.length && <p className="mai-empty">No transcript.</p>}
                {segments.map((s, i) => (
                  <div key={s.id} data-seg={i}
                    className={`mai-seg ${i === activeSegIdx ? "is-active" : ""}`}
                    onClick={() => { seek(s.start_ms); docId && recordInteraction(workspaceId, { event_type: "transcript_click", document_id: docId, position_ms: s.start_ms }); }}>
                    <span className="mai-seg-t">{fmtTime(s.start_ms)}</span>
                    <span className="mai-seg-spk">{s.speaker_label}</span>
                    <span className="mai-seg-x">{s.text}</span>
                  </div>
                ))}
              </section>
            </>
          )}
        </main>

        {/* right: AI actions + chat */}
        <aside className="mai-side">
          <section className="mai-actions">
            <h3>AI actions</h3>
            <div className="mai-action-grid">
              {AI_ACTIONS.map((a) => (
                <button key={a.action} className="mai-action" disabled={!docId} onClick={() => doAction(a.action)}>
                  <span>{a.icon}</span>{a.label}
                </button>
              ))}
            </div>
          </section>
          <MediaChatPanel ws={workspaceId} docId={docId} onSeek={(ms) => seek(ms)} />
        </aside>
      </div>
    </div>
  );
}

// ---- chat panel (reuses the backend media chat, which reuses the chat pipeline) ------------
function MediaChatPanel({ ws, docId, onSeek }: { ws: string; docId: string | null; onSeek: (ms: number) => void }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState<string | undefined>(undefined);

  // reset the thread when switching recordings
  useEffect(() => { setTurns([]); setConvId(undefined); }, [docId]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", content: q }]);
    setBusy(true);
    try {
      const res = await mediaChat(ws, { content: q, conversation_id: convId, document_id: docId ?? undefined });
      setConvId(res.conversation_id);
      setTurns((t) => [...t, { role: "assistant", content: res.answer, citations: res.citations, grounded: res.grounded }]);
    } catch (err) {
      setTurns((t) => [...t, { role: "assistant", content: err instanceof ApiError ? err.message : "Chat failed." }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mai-chat">
      <h3>Ask this recording</h3>
      <div className="mai-chat-log">
        {!turns.length && <p className="mai-empty">e.g. “What did the speaker say about deadlocks?” · “Summarize chapter 1.” · “What happened after that?”</p>}
        {turns.map((t, i) => (
          <div key={i} className={`mai-turn mai-turn--${t.role}`}>
            <div className="mai-turn-body">{t.content}</div>
            {t.role === "assistant" && t.grounded === false && <div className="mai-turn-note">no media evidence found</div>}
            {t.citations && t.citations.length > 0 && (
              <div className="mai-cites">
                {t.citations.map((c, j) => (
                  <button key={j} className="mai-cite" title={c.text} onClick={() => c.document_id && onSeek(c.start_ms)}>
                    ⏱ {c.timespan}{c.speaker_label ? ` · ${c.speaker_label}` : ""}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="mai-turn mai-turn--assistant"><div className="mai-turn-body">…</div></div>}
      </div>
      <form className="mai-chat-bar" onSubmit={send}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question…" disabled={busy} />
        <button type="submit" disabled={busy || !input.trim()}>Ask</button>
      </form>
    </section>
  );
}
