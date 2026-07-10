// Right-click context menu for the PDF viewer. Same extensible `onAction(type, text)` contract as
// the selection toolbar. Closes on Escape or any outside click.

import { useEffect, useRef } from "react";
import { CONTEXT_ACTIONS } from "./actions";
import type { ViewerActionType } from "./actions";

interface Props {
  x: number;
  y: number;
  text: string;
  onAction: (type: ViewerActionType, text: string) => void;
  onClose: () => void;
}

export default function ContextMenu({ x, y, text, onAction, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const hasText = text.trim().length > 0;

  return (
    <div
      ref={ref}
      className="pdf-context-menu"
      style={{ left: `${x}px`, top: `${y}px` }}
      role="menu"
    >
      {CONTEXT_ACTIONS.map((a) => (
        <button
          key={a.type}
          className="pdf-context-item"
          role="menuitem"
          disabled={!hasText}
          title={a.live ? a.label : `${a.label} (coming soon)`}
          onClick={() => {
            onAction(a.type, text);
            onClose();
          }}
        >
          <span aria-hidden="true" className="pdf-context-icon">{a.icon}</span>
          {a.label}
          {!a.live && <span className="pdf-context-soon">soon</span>}
        </button>
      ))}
    </div>
  );
}
