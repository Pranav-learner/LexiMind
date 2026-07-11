// The active-recall review screen. Route: /workspace/:workspaceId/flashcards/review?deck=<id?>
//
// Serves one card at a time from the SM-2 review queue. The user reads the front, flips (Space) to
// reveal the answer + hint, then grades recall with Again/Hard/Good/Easy (keys 1–4). Each button
// shows the interval it would schedule. Tracks response time per card, a session progress bar and
// stats, a citation panel (click → open the PDF at the page), and per-card favorite/suspend. When
// the queue drains it fetches more; when nothing is due it shows a "done" screen.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as fc from "../api/flashcards";
import { getDocumentByVector } from "../api/viewer";
import { ApiError } from "../api/client";
import { CARD_TYPE_META, RATINGS } from "../components/flashcards/constants";
import type { FlashcardCitationT, ReviewCardT, ReviewRating } from "../types";

export default function ReviewSession() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const deckId = params.get("deck") || undefined;

  const [queue, setQueue] = useState<ReviewCardT[]>([]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  // Session stats.
  const [reviewed, setReviewed] = useState(0);
  const [correct, setCorrect] = useState(0);
  const [totalDue, setTotalDue] = useState(0);
  const shownAtRef = useRef<number>(Date.now());

  const current = queue[index] || null;

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = await fc.getReviewQueue(workspaceId, { deck_id: deckId, limit: 50 });
      setQueue(q.cards);
      setIndex(0);
      setFlipped(false);
      setShowHint(false);
      setTotalDue(q.total_due);
      setDone(q.cards.length === 0);
      shownAtRef.current = Date.now();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load review queue.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, deckId]);

  useEffect(() => { loadQueue(); }, [loadQueue]);

  const grade = useCallback(async (rating: ReviewRating) => {
    if (!current || busy) return;
    setBusy(true);
    const rt = Date.now() - shownAtRef.current;
    try {
      const res = await fc.submitReview(workspaceId, current.card.id, rating, rt);
      setReviewed((n) => n + 1);
      if (rating !== "again") setCorrect((n) => n + 1);
      const next = index + 1;
      if (next >= queue.length) {
        // Queue drained — try to fetch more due/new cards; otherwise finish.
        const q = await fc.getReviewQueue(workspaceId, { deck_id: deckId, limit: 50 });
        if (q.cards.length === 0) { setDone(true); }
        else { setQueue(q.cards); setIndex(0); }
      } else {
        setIndex(next);
      }
      setFlipped(false);
      setShowHint(false);
      shownAtRef.current = Date.now();
      void res;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit review.");
    } finally {
      setBusy(false);
    }
  }, [current, busy, index, queue.length, workspaceId, deckId]);

  // Keyboard: Space/Enter flips; 1–4 grade (only after flip); H toggles hint.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (done || !current) return;
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); setFlipped((f) => !f); return; }
      if (e.key.toLowerCase() === "h") { setShowHint((h) => !h); return; }
      if (flipped) {
        const r = RATINGS.find((x) => x.key === e.key);
        if (r) { e.preventDefault(); grade(r.rating); }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flipped, done, current, grade]);

  const onCitation = useCallback(async (c: FlashcardCitationT) => {
    if (!c.document_id) return;
    try {
      const doc = await getDocumentByVector(workspaceId, c.document_id);
      navigate(`/workspace/${workspaceId}/document/${doc.id}`, { state: { citation: { page: c.page_number, text: c.citation_text } } });
    } catch { /* best effort */ }
  }, [navigate, workspaceId]);

  const accuracy = reviewed ? Math.round((correct / reviewed) * 100) : 0;
  const progress = totalDue ? Math.min(100, Math.round((reviewed / Math.max(totalDue, reviewed)) * 100)) : 0;
  const buttonFor = useMemo(() => new Map((current?.buttons || []).map((b) => [b.rating, b])), [current]);

  if (loading) {
    return <div className="fc-review-page"><div className="sum-viewer-status"><span className="ws-brand-mark spin">🧠</span><p>Loading review…</p></div></div>;
  }

  if (done) {
    return (
      <div className="fc-review-page">
        <div className="fc-review-done">
          <div className="ws-empty-mark">🎉</div>
          <h2>{reviewed > 0 ? "Session complete!" : "Nothing due right now"}</h2>
          {reviewed > 0 && <p>Reviewed <strong>{reviewed}</strong> cards · <strong>{accuracy}%</strong> accuracy</p>}
          <p className="fc-review-done-sub">Spaced repetition will resurface these cards right before you'd forget them.</p>
          <div className="fc-review-done-actions">
            <button className="ws-btn ghost" onClick={loadQueue}>↻ Check again</button>
            <Link className="ws-btn primary" to={`/workspace/${workspaceId}/flashcards`}>← Back to decks</Link>
          </div>
        </div>
      </div>
    );
  }

  if (!current) return null;
  const card = current.card;

  return (
    <div className="fc-review-page">
      <header className="fc-review-header">
        <Link className="ws-back" to={`/workspace/${workspaceId}/flashcards`}>✕ Exit</Link>
        <div className="fc-review-progress">
          <div className="fc-review-bar"><div className="fc-review-bar-fill" style={{ width: `${progress}%` }} /></div>
          <span className="fc-review-count">{reviewed} done · {accuracy}% · {Math.max(0, totalDue - reviewed)} left</span>
        </div>
        <div className="fc-review-tools">
          <button className="ws-icon-btn" title={card.is_favorite ? "Unfavorite" : "Favorite"} onClick={() => fc.updateCard(workspaceId, card.id, { is_favorite: !card.is_favorite }).catch(() => {})}>{card.is_favorite ? "⭐" : "☆"}</button>
          <button className="ws-icon-btn" title="Suspend card" onClick={() => fc.suspendCard(workspaceId, card.id).then(() => grade("good")).catch(() => {})}>⏸</button>
        </div>
      </header>

      {error && <div className="ws-error-banner" style={{ margin: "8px 20px 0" }}>{error}</div>}

      <div className="fc-review-stage">
        <div className={`fc-flashcard${flipped ? " flipped" : ""}`} onClick={() => setFlipped((f) => !f)}>
          <div className="fc-flashcard-inner">
            <div className="fc-flashcard-face front">
              <span className="fc-card-type-badge">{CARD_TYPE_META[card.card_type]?.icon} {CARD_TYPE_META[card.card_type]?.label}</span>
              <p className="fc-face-text">{card.front}</p>
              {card.hint && (
                <button className="fc-hint-toggle" onClick={(e) => { e.stopPropagation(); setShowHint((h) => !h); }}>
                  {showHint ? `💡 ${card.hint}` : "💡 Show hint (H)"}
                </button>
              )}
              <span className="fc-flip-hint">Tap or press Space to flip</span>
            </div>
            <div className="fc-flashcard-face back">
              <p className="fc-face-text">{card.back || card.front}</p>
              {card.citations.length > 0 && (
                <div className="fc-citation-strip" onClick={(e) => e.stopPropagation()}>
                  {card.citations.map((c, i) => (
                    <button key={c.id} className="chat-citation sm" onClick={() => onCitation(c)} disabled={!c.document_id} title="Open source">
                      <span className="chat-citation-head">
                        <span aria-hidden="true">📄</span><span className="chat-citation-num">[{i + 1}]</span>
                        {c.page_number != null && <span className="chat-citation-page">p.{c.page_number}</span>}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <footer className="fc-review-footer">
        {!flipped ? (
          <button className="ws-btn primary fc-reveal-btn" onClick={() => setFlipped(true)}>Show answer <kbd>Space</kbd></button>
        ) : (
          <div className="fc-rating-row">
            {RATINGS.map((r) => (
              <button key={r.rating} className="fc-rating-btn" style={{ ["--rating" as string]: r.color }}
                      disabled={busy} onClick={() => grade(r.rating)}>
                <span className="fc-rating-label">{r.label}</span>
                <span className="fc-rating-interval">{buttonFor.get(r.rating)?.label || ""}</span>
                <kbd>{r.key}</kbd>
              </button>
            ))}
          </div>
        )}
      </footer>
    </div>
  );
}
