// The Flashcards & Active Recall dashboard. Route: /workspace/:workspaceId/flashcards
//
// Top: learning analytics (streak, due, accuracy, retention, activity chart) + a "Study all due"
// CTA. Below: a grid of DeckCard with a "New deck" button (opens GenerateDeckModal: empty deck or
// AI-generated). Opening a deck navigates to the deck view; "Study" starts a review session.
// Honors a "make flashcards from this" hand-off (document/note/summary/chat) via router state.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import * as fc from "../api/flashcards";
import { getWorkspace } from "../api/workspaces";
import { ApiError } from "../api/client";
import DeckCard from "../components/flashcards/DeckCard";
import GenerateDeckModal from "../components/flashcards/GenerateDeckModal";
import AnalyticsPanel from "../components/flashcards/AnalyticsPanel";
import type { Deck, DeckGenerateInput, LearningAnalytics, Workspace } from "../types";

interface PresetState {
  makeFlashcards?: { document_id?: string; note_id?: string; summary_id?: string; conversation_id?: string };
}

export default function FlashcardsDashboard() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [decks, setDecks] = useState<Deck[]>([]);
  const [analytics, setAnalytics] = useState<LearningAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showModal, setShowModal] = useState(false);
  const [presetDocId, setPresetDocId] = useState<string | undefined>();
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const openDeck = useCallback((id: string) => navigate(`/workspace/${workspaceId}/flashcards/deck/${id}`), [navigate, workspaceId]);
  const study = useCallback((deckId?: string) => navigate(`/workspace/${workspaceId}/flashcards/review${deckId ? `?deck=${deckId}` : ""}`), [navigate, workspaceId]);

  useEffect(() => {
    let alive = true;
    getWorkspace(workspaceId).then((w) => alive && setWorkspace(w)).catch(() => {});
    return () => { alive = false; };
  }, [workspaceId]);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const [deckRes, an] = await Promise.all([
        fc.listDecks(workspaceId, { page_size: 60, sort_by: "updated_at", order: "desc" }, controller.signal),
        fc.getAnalytics(workspaceId, 30, controller.signal),
      ]);
      setDecks(deckRes.items);
      setAnalytics(an);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load flashcards.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [load]);

  // Hand-off from Notes/Summary/Chat/Library ("make flashcards from this").
  useEffect(() => {
    const preset = (location.state as PresetState | null)?.makeFlashcards;
    if (!preset) return;
    navigate(location.pathname, { replace: true, state: null });
    (async () => {
      try {
        let deck: Deck | null = null;
        if (preset.note_id) deck = await fc.deckFromNote(workspaceId, preset.note_id);
        else if (preset.summary_id) deck = await fc.deckFromSummary(workspaceId, preset.summary_id);
        else if (preset.conversation_id) deck = await fc.deckFromChat(workspaceId, preset.conversation_id);
        else if (preset.document_id) { setPresetDocId(preset.document_id); setShowModal(true); return; }
        if (deck) openDeck(deck.id);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not create deck.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleEmpty(name: string) {
    setCreating(true); setCreateError(null);
    try {
      const d = await fc.createDeck(workspaceId, { name: name || undefined });
      setShowModal(false);
      openDeck(d.id);
    } catch (err) { setCreateError(err instanceof ApiError ? err.message : "Failed to create deck."); }
    finally { setCreating(false); }
  }

  async function handleGenerate(payload: DeckGenerateInput) {
    setCreating(true); setCreateError(null);
    try {
      const d = await fc.generateDeck(workspaceId, payload);
      setShowModal(false); setPresetDocId(undefined);
      openDeck(d.id);
    } catch (err) { setCreateError(err instanceof ApiError ? err.message : "Failed to start generation."); }
    finally { setCreating(false); }
  }

  async function confirmDelete(d: Deck) {
    if (!window.confirm(`Delete deck "${d.name}" and its cards? (soft delete)`)) return;
    try { await fc.deleteDeck(workspaceId, d.id); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Delete failed."); }
  }

  const totalDue = analytics ? analytics.due_today + analytics.new_cards : 0;

  return (
    <div className="ws-page sum-page fc-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: workspace?.color || "" }}>
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {workspace?.name || "Workspace"}</Link>
        <div className="ws-header-right">
          {totalDue > 0 && (
            <button className="ws-btn primary fc-study-all" onClick={() => study()}>🎓 Study {totalDue} due</button>
          )}
          <button className="ws-btn primary" onClick={() => { setPresetDocId(undefined); setCreateError(null); setShowModal(true); }}>＋ New deck</button>
        </div>
      </header>

      <div className="sum-list-col fc-list-col">
        <div className="ws-page-title">
          <div>
            <h1>🎴 Flashcards</h1>
            <p>Active recall & spaced repetition</p>
          </div>
        </div>

        {error && <div className="ws-error-banner">{error}</div>}
        {analytics && <AnalyticsPanel a={analytics} />}

        <h2 className="fc-section-title">Decks</h2>
        {loading ? (
          <div className="ws-grid sum-grid">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="ws-card skeleton" />)}</div>
        ) : decks.length === 0 ? (
          <div className="ws-empty">
            <div className="ws-empty-mark">🎴</div>
            <h3>No decks yet</h3>
            <p>Generate flashcards from a document, or build a deck by hand.</p>
            <button className="ws-btn primary" onClick={() => setShowModal(true)}>＋ New deck</button>
          </div>
        ) : (
          <div className="ws-grid sum-grid fc-deck-grid">
            {decks.map((d) => (
              <DeckCard key={d.id} deck={d} onOpen={(x) => openDeck(x.id)} onStudy={(x) => study(x.id)}
                        onExport={(x) => fc.exportDeck(workspaceId, x.id, "csv", `${x.name}.csv`).catch(() => {})}
                        onDelete={confirmDelete} />
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <GenerateDeckModal
          workspaceId={workspaceId}
          initialDocumentId={presetDocId}
          submitting={creating}
          serverError={createError}
          onEmpty={handleEmpty}
          onGenerate={handleGenerate}
          onClose={() => { setShowModal(false); setPresetDocId(undefined); }}
        />
      )}
    </div>
  );
}
