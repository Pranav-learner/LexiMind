// The viewer's top toolbar. Purely presentational — every action is lifted to the parent via a
// callback prop. Groups: sidebar toggle, page nav + jump, zoom (in/out/fit-width/fit-page/reset),
// rotate, search, fullscreen, download/print, AI panel toggle.

import { useEffect, useState } from "react";

interface Props {
  title: string;
  page: number;
  numPages: number;
  onPage: (n: number) => void;
  zoomPercent: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitWidth: () => void;
  onFitPage: () => void;
  onResetZoom: () => void;
  onRotateLeft: () => void;
  onRotateRight: () => void;
  searchOpen: boolean;
  onToggleSearch: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onDownload: () => void;
  onPrint: () => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  aiPanelOpen: boolean;
  onToggleAiPanel: () => void;
  onBack: () => void;
}

export default function PdfToolbar(props: Props) {
  const {
    title,
    page,
    numPages,
    onPage,
    zoomPercent,
    onZoomIn,
    onZoomOut,
    onFitWidth,
    onFitPage,
    onResetZoom,
    onRotateLeft,
    onRotateRight,
    searchOpen,
    onToggleSearch,
    fullscreen,
    onToggleFullscreen,
    onDownload,
    onPrint,
    sidebarOpen,
    onToggleSidebar,
    aiPanelOpen,
    onToggleAiPanel,
    onBack,
  } = props;

  const [pageInput, setPageInput] = useState(String(page));
  useEffect(() => setPageInput(String(page)), [page]);

  function commitPage() {
    const n = parseInt(pageInput, 10);
    if (!Number.isNaN(n) && n >= 1 && n <= numPages) onPage(n);
    else setPageInput(String(page));
  }

  return (
    <div className="pdf-toolbar">
      <div className="pdf-toolbar-group">
        <button className="ws-icon-btn" title="Back" aria-label="Back" onClick={onBack}>←</button>
        <button
          className={`ws-icon-btn ${sidebarOpen ? "active" : ""}`}
          title="Toggle sidebar"
          aria-label="Toggle sidebar"
          aria-pressed={sidebarOpen}
          onClick={onToggleSidebar}
        >
          ☰
        </button>
        <span className="pdf-toolbar-title" title={title}>{title}</span>
      </div>

      <div className="pdf-toolbar-group">
        <button className="ws-icon-btn" title="Previous page" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>◀</button>
        <input
          className="pdf-page-input"
          value={pageInput}
          aria-label="Page number"
          onChange={(e) => setPageInput(e.target.value)}
          onBlur={commitPage}
          onKeyDown={(e) => e.key === "Enter" && commitPage()}
        />
        <span className="pdf-page-total">/ {numPages || "—"}</span>
        <button className="ws-icon-btn" title="Next page" aria-label="Next page" disabled={page >= numPages} onClick={() => onPage(page + 1)}>▶</button>
      </div>

      <div className="pdf-toolbar-group">
        <button className="ws-icon-btn" title="Zoom out" aria-label="Zoom out" onClick={onZoomOut}>−</button>
        <span className="pdf-zoom-label" aria-live="polite">{zoomPercent}%</span>
        <button className="ws-icon-btn" title="Zoom in" aria-label="Zoom in" onClick={onZoomIn}>+</button>
        <button className="ws-icon-btn" title="Fit width" aria-label="Fit width" onClick={onFitWidth}>↔</button>
        <button className="ws-icon-btn" title="Fit page" aria-label="Fit page" onClick={onFitPage}>⤢</button>
        <button className="ws-icon-btn" title="Reset zoom (100%)" aria-label="Reset zoom" onClick={onResetZoom}>⟲%</button>
      </div>

      <div className="pdf-toolbar-group">
        <button className="ws-icon-btn" title="Rotate left" aria-label="Rotate left" onClick={onRotateLeft}>⟲</button>
        <button className="ws-icon-btn" title="Rotate right" aria-label="Rotate right" onClick={onRotateRight}>⟳</button>
      </div>

      <div className="pdf-toolbar-group pdf-toolbar-right">
        <button className={`ws-icon-btn ${searchOpen ? "active" : ""}`} title="Search (Ctrl+F)" aria-label="Search" aria-pressed={searchOpen} onClick={onToggleSearch}>🔍</button>
        <button className="ws-icon-btn" title="Fullscreen" aria-label="Fullscreen" aria-pressed={fullscreen} onClick={onToggleFullscreen}>{fullscreen ? "🗗" : "⛶"}</button>
        <button className="ws-icon-btn" title="Download" aria-label="Download" onClick={onDownload}>⬇</button>
        <button className="ws-icon-btn" title="Print" aria-label="Print" onClick={onPrint}>🖨</button>
        <button className={`ws-icon-btn ${aiPanelOpen ? "active" : ""}`} title="AI assistant" aria-label="AI assistant" aria-pressed={aiPanelOpen} onClick={onToggleAiPanel}>✨</button>
      </div>
    </div>
  );
}
