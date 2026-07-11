// A compact citation card rendered under an assistant message. Shows the source snippet, page,
// and a confidence bar. Clicking it triggers citation navigation (resolve vector id → open the
// document viewer, jump to the page, highlight the text) handled by the parent.

import { memo } from "react";
import type { ChatCitation } from "../../types";

interface Props {
  citation: ChatCitation;
  index: number;
  onClick: (c: ChatCitation) => void;
  onExplore?: (c: ChatCitation) => void; // Module 8: open the Citation Intelligence panel
}

function CitationCardBase({ citation, index, onClick, onExplore }: Props) {
  const pct = Math.round(Math.max(0, Math.min(1, citation.confidence || 0)) * 100);
  const snippet = citation.citation_text || "Cited source";
  return (
    <button
      type="button"
      className="chat-citation"
      title={`Open source · page ${citation.page_number}`}
      aria-label={`Open citation ${index + 1}, page ${citation.page_number}, confidence ${pct}%`}
      onClick={() => onClick(citation)}
    >
      <span className="chat-citation-head">
        <span className="chat-citation-icon" aria-hidden="true">📄</span>
        <span className="chat-citation-num">[{index + 1}]</span>
        <span className="chat-citation-page">Page {citation.page_number}</span>
        <span className="chat-citation-conf">{pct}%</span>
        {onExplore && (
          <span
            className="chat-citation-explore"
            role="button"
            tabIndex={0}
            title="Explore this citation (Knowledge Explorer)"
            aria-label="Explore citation"
            onClick={(e) => { e.stopPropagation(); onExplore(citation); }}
            onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onExplore(citation); } }}
          >
            🔎
          </span>
        )}
      </span>
      <span className="chat-citation-text">{snippet}</span>
      <span className="chat-citation-bar" aria-hidden="true">
        <span className="chat-citation-bar-fill" style={{ width: `${pct}%` }} />
      </span>
    </button>
  );
}

export default memo(CitationCardBase);
