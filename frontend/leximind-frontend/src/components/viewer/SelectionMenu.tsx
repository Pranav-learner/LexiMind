// Floating toolbar that appears above a text selection in the PDF. Presentational: it renders the
// SELECTION_ACTIONS and lifts each click via `onAction(type, text)`. Positioned at the caller-
// supplied viewport coordinates; closes on outside click / Escape (handled by the parent).

import { SELECTION_ACTIONS } from "./actions";
import type { ViewerActionType } from "./actions";

interface Props {
  x: number;
  y: number;
  text: string;
  onAction: (type: ViewerActionType, text: string) => void;
}

export default function SelectionMenu({ x, y, text, onAction }: Props) {
  return (
    <div
      className="pdf-selection-menu"
      style={{ left: `${x}px`, top: `${y}px` }}
      role="toolbar"
      aria-label="Selection actions"
      // Keep the browser selection alive while clicking the toolbar.
      onMouseDown={(e) => e.preventDefault()}
    >
      {SELECTION_ACTIONS.map((a) => (
        <button
          key={a.type}
          className="pdf-selection-btn"
          title={a.live ? a.label : `${a.label} (coming soon)`}
          onClick={() => onAction(a.type, text)}
        >
          <span aria-hidden="true">{a.icon}</span>
          {a.label}
        </button>
      ))}
    </div>
  );
}
