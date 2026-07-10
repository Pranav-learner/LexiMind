// Right-hand AI assistant panel. Reuses the existing `askQuestion` → POST /query retrieval (never
// re-implements retrieval). Two modes: a free-form question box, and "Ask about selection" which
// prefills + auto-submits the currently-selected passage. Renders the answer and clickable
// citation chips built from the response `citations`; clicking a chip bubbles up via `onCitation`.

import { useEffect, useRef, useState } from "react";
import { askQuestion } from "../../api/backend";
import type { QueryCitation, QueryResponse } from "../../types";

interface Props {
  workspaceId: string;
  // A selection the user asked about; changing `id` re-triggers a prefilled auto-submit.
  pendingAsk: { text: string; id: number } | null;
  onCitation: (citation: QueryCitation) => void;
  onClose: () => void;
}

export default function AiPanel({ workspaceId, pendingAsk, onCitation, onClose }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [citations, setCitations] = useState<QueryCitation[]>([]);
  const lastAsk = useRef<number>(0);

  async function submit(q: string) {
    const query = q.trim();
    if (!query || loading) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    setCitations([]);
    try {
      const res = (await askQuestion(query, workspaceId)) as QueryResponse;
      setAnswer(res.answer ?? "");
      setCitations(Array.isArray(res.citations) ? res.citations : []);
    } catch {
      setError("Query failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  // Prefill + auto-submit when the user asks about a selection.
  useEffect(() => {
    if (pendingAsk && pendingAsk.id !== lastAsk.current) {
      lastAsk.current = pendingAsk.id;
      const q = `Explain this passage: "${pendingAsk.text}"`;
      setQuestion(q);
      submit(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAsk]);

  return (
    <aside className="pdf-ai-panel" aria-label="AI assistant">
      <div className="pdf-ai-header">
        <h3>✨ AI Assistant</h3>
        <button className="ws-icon-btn" title="Close" aria-label="Close AI panel" onClick={onClose}>✕</button>
      </div>

      <form
        className="pdf-ai-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
      >
        <textarea
          className="pdf-ai-input"
          rows={3}
          placeholder="Ask a question about this document…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit(question);
            }
          }}
        />
        <button className="ws-btn primary" type="submit" disabled={loading || !question.trim()}>
          {loading ? "Thinking…" : "Ask"}
        </button>
      </form>

      <div className="pdf-ai-body">
        {error && <div className="ws-error-banner">{error}</div>}
        {loading && <p className="doc-muted">Retrieving an answer…</p>}
        {answer != null && !loading && (
          <div className="pdf-ai-answer">
            <p className="pdf-ai-answer-text">{answer}</p>
            {citations.length > 0 && (
              <div className="pdf-ai-citations">
                <span className="pdf-ai-citations-label">Sources</span>
                <div className="pdf-ai-chips">
                  {citations.map((c, i) => (
                    <button
                      key={c.chunk_id || i}
                      className="pdf-citation-chip"
                      title={c.text}
                      onClick={() => onCitation(c)}
                    >
                      <span className="pdf-chip-num">{i + 1}</span>
                      <span className="pdf-chip-src">{c.source}</span>
                      <span className="pdf-chip-page">p.{c.page_number}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {answer == null && !loading && !error && (
          <p className="doc-muted pdf-ai-hint">
            Ask anything about this document, or select text and choose “Ask AI”. Answers cite the
            exact pages — click a source to jump there.
          </p>
        )}
      </div>
    </aside>
  );
}
