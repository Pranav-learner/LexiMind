// A single deck. Route: /workspace/:workspaceId/flashcards/deck/:deckId
//
// Header (name + stats + Study/Export/Delete), a card list with per-card actions (edit, suspend,
// reset, favorite, delete), and "Add card" / "Generate more" actions. If the deck is still
// generating it polls to a terminal state and streams in cards.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as fc from "../api/flashcards";
import { ApiError } from "../api/client";
import CardFormModal from "../components/flashcards/CardFormModal";
import { CARD_TYPE_META, masteryLabel, relativeTime } from "../components/flashcards/constants";
import type { CardType, Deck, Flashcard } from "../types";

export default function DeckView() {
  const { workspaceId = "", deckId = "" } = useParams();
  const navigate = useNavigate();

  const [deck, setDeck] = useState<Deck | null>(null);
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Flashcard | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadCards = useCallback(async (signal?: AbortSignal) => {
    const res = await fc.listCards(workspaceId, { deck_id: deckId, page_size: 200, sort_by: "created_at", order: "asc" }, signal);
    setCards(res.items);
  }, [workspaceId, deckId]);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      let d = await fc.getDeck(workspaceId, deckId, controller.signal);
      setDeck(d);
      if (!fc.isTerminal(d.status)) {
        await fc.pollDeckStatus(workspaceId, deckId, {
          signal: controller.signal,
          onUpdate: (x) => { setDeck((p) => (p ? { ...p, ...x } : p)); loadCards(controller.signal).catch(() => {}); },
        });
        d = await fc.getDeck(workspaceId, deckId, controller.signal);
        setDeck(d);
      }
      await loadCards(controller.signal);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load deck.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, deckId, loadCards]);

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [load]);

  async function submitCard(data: { front: string; back: string; hint: string; card_type: CardType }) {
    setSaving(true); setFormError(null);
    try {
      if (editing) await fc.updateCard(workspaceId, editing.id, data);
      else await fc.createCard(workspaceId, { deck_id: deckId, ...data });
      setShowForm(false); setEditing(null);
      await load();
    } catch (err) { setFormError(err instanceof ApiError ? err.message : "Save failed."); }
    finally { setSaving(false); }
  }

  async function act(fn: () => Promise<unknown>) {
    try { await fn(); await load(); } catch (err) { setError(err instanceof ApiError ? err.message : "Action failed."); }
  }

  async function regenerate() {
    try { await fc.regenerateDeck(workspaceId, deckId); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Regenerate failed."); }
  }

  if (loading && !deck) return <div className="note-editor-page"><div className="sum-viewer-status"><span className="ws-brand-mark spin">🧠</span><p>Loading deck…</p></div></div>;
  if (!deck) return <div className="note-editor-page"><div className="sum-viewer-status"><div className="ws-error-banner">{error || "Deck not found."}</div><Link className="ws-btn ghost" to={`/workspace/${workspaceId}/flashcards`}>← Back</Link></div></div>;

  const generating = deck.status === "queued" || deck.status === "processing";
  const s = deck.stats;

  return (
    <div className="ws-page sum-page fc-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: deck.color }}>
        <Link className="ws-back" to={`/workspace/${workspaceId}/flashcards`}>← Flashcards</Link>
        <div className="ws-detail-title">
          <span className="ws-card-icon" style={{ background: deck.color }}>{deck.icon}</span>
          <div><h1>{deck.name}</h1>{deck.description && <p>{deck.description}</p>}</div>
        </div>
        <div className="ws-header-right">
          <button className="ws-btn primary" disabled={deck.card_count === 0} onClick={() => navigate(`/workspace/${workspaceId}/flashcards/review?deck=${deckId}`)}>🎓 Study</button>
          {deck.created_by === "ai" && <button className="ws-btn ghost" onClick={regenerate} disabled={generating}>🔄 Regenerate</button>}
          <button className="ws-btn ghost" onClick={() => fc.exportDeck(workspaceId, deckId, "csv", `${deck.name}.csv`).catch(() => {})}>⬇ Export</button>
        </div>
      </header>

      <div className="sum-list-col fc-list-col">
        {error && <div className="ws-error-banner">{error}</div>}

        {s && (
          <div className="fc-deck-stats wide">
            <MiniStat label="Total" value={s.total} />
            <MiniStat label="New" value={s.new} />
            <MiniStat label="Due" value={s.due} />
            <MiniStat label="Mastered" value={s.mastered} />
            <MiniStat label="Avg mastery" value={`${Math.round(s.avg_mastery * 100)}%`} />
          </div>
        )}

        <div className="ws-page-title">
          <h2 className="fc-section-title">Cards ({deck.card_count})</h2>
          <button className="ws-btn primary" onClick={() => { setEditing(null); setFormError(null); setShowForm(true); }}>＋ Add card</button>
        </div>

        {generating && (
          <div className="fc-generating-banner">
            <span className="ws-brand-mark spin">🧠</span> Generating cards… {deck.progress}%
            <button className="ws-link" onClick={() => fc.cancelDeck(workspaceId, deckId).catch(() => {})}>Cancel</button>
          </div>
        )}

        {cards.length === 0 && !generating ? (
          <div className="ws-empty"><div className="ws-empty-mark">📇</div><h3>No cards yet</h3><p>Add a card to get started.</p></div>
        ) : (
          <div className="fc-card-list">
            {cards.map((c) => (
              <div key={c.id} className={`fc-card-row${c.status === "suspended" ? " suspended" : ""}`}>
                <div className="fc-card-row-main">
                  <span className="fc-card-type-badge">{CARD_TYPE_META[c.card_type]?.icon} {CARD_TYPE_META[c.card_type]?.label}</span>
                  <div className="fc-card-qa">
                    <p className="fc-card-front">{c.front}</p>
                    <p className="fc-card-back">{c.back || <em>(cloze)</em>}</p>
                  </div>
                </div>
                <div className="fc-card-row-meta">
                  <span className={`fc-mastery-tag m-${masteryLabel(c.mastery_score).toLowerCase()}`}>{masteryLabel(c.mastery_score)}</span>
                  <span className="fc-card-next">{c.next_review_at ? `next ${relativeTime(c.next_review_at)}` : "unseen"}</span>
                </div>
                <div className="fc-card-row-actions">
                  <button className="ws-icon-btn" title={c.is_favorite ? "Unfavorite" : "Favorite"} onClick={() => act(() => fc.updateCard(workspaceId, c.id, { is_favorite: !c.is_favorite }))}>{c.is_favorite ? "⭐" : "☆"}</button>
                  <button className="ws-icon-btn" title="Edit" onClick={() => { setEditing(c); setFormError(null); setShowForm(true); }}>✏️</button>
                  <button className="ws-icon-btn" title={c.status === "suspended" ? "Unsuspend" : "Suspend"} onClick={() => act(() => c.status === "suspended" ? fc.unsuspendCard(workspaceId, c.id) : fc.suspendCard(workspaceId, c.id))}>{c.status === "suspended" ? "▶️" : "⏸"}</button>
                  <button className="ws-icon-btn" title="Reset progress" onClick={() => act(() => fc.resetCard(workspaceId, c.id))}>↺</button>
                  <button className="ws-icon-btn" title="Delete" onClick={() => window.confirm("Delete this card?") && act(() => fc.deleteCard(workspaceId, c.id))}>🗑</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showForm && (
        <CardFormModal card={editing} submitting={saving} error={formError} onSubmit={submitCard} onClose={() => { setShowForm(false); setEditing(null); }} />
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number | string }) {
  return <div className="ws-stat"><span className="ws-stat-value">{value}</span><span className="ws-stat-label">{label}</span></div>;
}
