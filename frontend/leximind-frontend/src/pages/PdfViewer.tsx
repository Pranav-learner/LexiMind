// Intelligent PDF Viewer page (Phase 3, Module 3). Route: /workspace/:workspaceId/document/:documentId.
// Layout: Toolbar on top, then [Sidebar | Viewer | AI Panel]. Owns all viewer state (page, scale,
// rotation, search, selection, citations, panel visibility) and wires together the modular viewer
// components. Reuses the existing /query retrieval via the AI panel — never re-implements it.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import PdfToolbar from "../components/viewer/PdfToolbar";
import PdfCanvas from "../components/viewer/PdfCanvas";
import type { PdfCanvasHandle } from "../components/viewer/PdfCanvas";
import PdfSidebar from "../components/viewer/PdfSidebar";
import type { SectionEntry } from "../components/viewer/PdfSidebar";
import PdfSearch from "../components/viewer/PdfSearch";
import type { SearchMatch } from "../components/viewer/PdfSearch";
import SelectionMenu from "../components/viewer/SelectionMenu";
import ContextMenu from "../components/viewer/ContextMenu";
import AiPanel from "../components/viewer/AiPanel";
import { usePdfDocument } from "../components/viewer/usePdfDocument";
import { useCitationHighlight } from "../components/viewer/useCitationHighlight";
import { useReadingSession, readCachedSession } from "../components/viewer/useReadingSession";
import type { ViewerActionType } from "../components/viewer/actions";
import * as viewerApi from "../api/viewer";
import { createNote } from "../api/notes";
import type { QueryCitation } from "../types";

const MIN_SCALE = 0.25;
const MAX_SCALE = 5;
const ZOOM_STEP = 0.2;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export default function PdfViewer() {
  const { workspaceId = "", documentId = "" } = useParams();
  const navigate = useNavigate();
  // Key by document so all viewer state resets cleanly when navigating between documents.
  return (
    <ViewerInner
      key={`${workspaceId}:${documentId}`}
      ws={workspaceId}
      docId={documentId}
      navigate={navigate}
    />
  );
}

interface CitationNavState {
  citation?: { page: number; text: string };
}

function ViewerInner({
  ws,
  docId,
  navigate,
}: {
  ws: string;
  docId: string;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const location = useLocation();
  const { pdf, meta, numPages, outline, loading, error, getPage } = usePdfDocument(ws, docId);

  const cached = useMemo(() => readCachedSession(docId), [docId]);

  const [scale, setScale] = useState(cached ? cached.zoom / 100 : 1);
  const [rotation, setRotation] = useState(cached?.rotation ?? 0);
  const [currentPage, setCurrentPage] = useState(cached?.page ?? 1);
  const [progress, setProgress] = useState(0);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [aiPanelOpen, setAiPanelOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const [selMenu, setSelMenu] = useState<{ x: number; y: number; text: string } | null>(null);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; text: string } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const [searchMatches, setSearchMatches] = useState<SearchMatch[]>([]);
  const [activeSearch, setActiveSearch] = useState<SearchMatch | null>(null);
  const [pendingAsk, setPendingAsk] = useState<{ text: string; id: number } | null>(null);
  const [recentPages, setRecentPages] = useState<number[]>([]);
  const [sections, setSections] = useState<SectionEntry[]>([]);
  const [base, setBase] = useState<{ w: number; h: number } | null>(null);

  const canvasRef = useRef<PdfCanvasHandle>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const scrollTopRef = useRef(0);
  const didInitialScroll = useRef(false);
  const rafRef = useRef<number | null>(null);
  const askIdRef = useRef(0);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast((t) => (t === msg ? null : t)), 2500);
  }, []);

  // Base (unscaled) page dimensions for placeholder sizing + fit calculations.
  useEffect(() => {
    if (!pdf) return;
    let alive = true;
    getPage(1)
      .then((page) => {
        if (!alive) return;
        const vp = page.getViewport({ scale: 1, rotation: 0 });
        setBase({ w: vp.width, h: vp.height });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [pdf, getPage]);

  // Section list (outline fallback) from the chunk endpoint.
  useEffect(() => {
    let alive = true;
    viewerApi
      .getDocumentChunks(ws, docId)
      .then((res) => {
        if (!alive) return;
        const seen = new Map<string, number>();
        for (const c of res.items) {
          if (c.section && !seen.has(c.section)) seen.set(c.section, c.page_number);
        }
        const list = Array.from(seen, ([section, page]) => ({ section, page })).sort(
          (a, b) => a.page - b.page,
        );
        setSections(list);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [ws, docId]);

  // Navigate to a page + record it in "recent".
  const scrollToPage = useCallback((n: number) => {
    canvasRef.current?.scrollToPage(n);
    setCurrentPage(n);
    setRecentPages((prev) => [n, ...prev.filter((p) => p !== n)].slice(0, 15));
  }, []);

  const citation = useCitationHighlight({ scrollToPage });

  // Reading session restore + debounced save.
  const onRestore = useCallback(
    (s: { page: number; zoom: number; rotation: number; scrollTop: number }) => {
      setScale(s.zoom / 100);
      setRotation(s.rotation);
      setCurrentPage(s.page);
      requestAnimationFrame(() => canvasRef.current?.scrollToPage(s.page, false));
    },
    [],
  );
  useReadingSession(
    ws,
    docId,
    { page: currentPage, zoomPercent: Math.round(scale * 100), rotation, scrollTop: scrollTopRef.current },
    onRestore,
  );

  // Initial scroll to the cached page once the layout is ready.
  useEffect(() => {
    if (base && !didInitialScroll.current && currentPage > 1) {
      didInitialScroll.current = true;
      requestAnimationFrame(() => canvasRef.current?.scrollToPage(currentPage, false));
    } else if (base) {
      didInitialScroll.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  // Cross-document citation navigation passed via router state.
  useEffect(() => {
    const state = location.state as CitationNavState | null;
    const c = state?.citation;
    if (base && c) {
      citation.highlight({ page: c.page, text: c.text });
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  const onProgress = useCallback((scrollTop: number, percent: number) => {
    scrollTopRef.current = scrollTop;
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      setProgress(percent);
    });
  }, []);

  // ---- zoom / rotation -------------------------------------------------
  const zoomIn = useCallback(() => setScale((s) => clamp(s + ZOOM_STEP, MIN_SCALE, MAX_SCALE)), []);
  const zoomOut = useCallback(() => setScale((s) => clamp(s - ZOOM_STEP, MIN_SCALE, MAX_SCALE)), []);
  const resetZoom = useCallback(() => setScale(1), []);
  const fitWidth = useCallback(() => {
    if (!base) return;
    const vp = canvasRef.current?.getViewport();
    if (!vp) return;
    const pw = rotation % 180 !== 0 ? base.h : base.w;
    setScale(clamp((vp.width - 32) / pw, MIN_SCALE, MAX_SCALE));
  }, [base, rotation]);
  const fitPage = useCallback(() => {
    if (!base) return;
    const vp = canvasRef.current?.getViewport();
    if (!vp) return;
    const rot = rotation % 180 !== 0;
    const pw = rot ? base.h : base.w;
    const ph = rot ? base.w : base.h;
    setScale(clamp(Math.min((vp.width - 32) / pw, (vp.height - 32) / ph), MIN_SCALE, MAX_SCALE));
  }, [base, rotation]);
  const rotateLeft = useCallback(() => setRotation((r) => (r + 270) % 360), []);
  const rotateRight = useCallback(() => setRotation((r) => (r + 90) % 360), []);

  // ---- fullscreen ------------------------------------------------------
  const toggleFullscreen = useCallback(() => {
    const el = rootRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else el.requestFullscreen().catch(() => {});
  }, []);
  useEffect(() => {
    const onFs = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  // ---- download / print -----------------------------------------------
  const download = useCallback(() => {
    viewerApi
      .downloadDocumentFile(ws, docId, meta?.filename ?? "document.pdf")
      .catch(() => showToast("Download failed"));
  }, [ws, docId, meta, showToast]);

  const print = useCallback(async () => {
    try {
      const buf = await viewerApi.fetchDocumentFile(ws, docId);
      const url = URL.createObjectURL(new Blob([buf], { type: "application/pdf" }));
      const w = window.open(url);
      if (w) w.addEventListener("load", () => w.print());
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      showToast("Print failed");
    }
  }, [ws, docId, showToast]);

  // ---- selection & context actions ------------------------------------
  const handleAction = useCallback(
    (type: ViewerActionType, text: string) => {
      const trimmed = text.trim();
      switch (type) {
        case "copy":
          navigator.clipboard?.writeText(trimmed).then(
            () => showToast("Copied to clipboard"),
            () => showToast("Copy failed"),
          );
          break;
        case "ask-ai":
          setAiPanelOpen(true);
          setPendingAsk({ text: trimmed, id: ++askIdRef.current });
          break;
        case "highlight":
          citation.highlight({ page: currentPage, text: trimmed });
          showToast("Highlighted");
          break;
        case "note":
          // Module 6: create a note seeded with the selected text + a citation to this page, then
          // open the editor. Best-effort — a failure just shows a toast.
          createNote(ws, {
            source: "selection",
            title: `Note · p.${currentPage}`,
            content: `> ${trimmed}\n\n`,
            document_id: docId,
            citations: meta?.vector_document_id
              ? [{ document_id: meta.vector_document_id, page_number: currentPage, citation_text: trimmed.slice(0, 300) }]
              : undefined,
          }).then(
            (n) => navigate(`/workspace/${ws}/notes/${n.id}`),
            () => showToast("Could not create note"),
          );
          break;
        case "flashcard":
          showToast("Flashcards — coming soon");
          break;
        case "summary":
          showToast("Summaries — coming soon");
          break;
      }
      setSelMenu(null);
      setCtxMenu(null);
    },
    [citation, currentPage, showToast, ws, docId, meta, navigate],
  );

  const onViewerMouseUp = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
      setSelMenu(null);
      return;
    }
    const text = sel.toString().trim();
    if (!text) {
      setSelMenu(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelMenu({ x: rect.left + rect.width / 2, y: rect.top - 8, text });
  }, []);

  const onViewerContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const text = window.getSelection()?.toString().trim() ?? "";
    setSelMenu(null);
    setCtxMenu({ x: e.clientX, y: e.clientY, text });
  }, []);

  // ---- citation chip from AI panel ------------------------------------
  const handleCitation = useCallback(
    async (c: QueryCitation) => {
      if (meta && c.document_id === meta.vector_document_id) {
        citation.highlight({ page: c.page_number, text: c.text });
        return;
      }
      // A citation into a different document — resolve the vector id and navigate.
      try {
        const doc = await viewerApi.getDocumentByVector(ws, c.document_id);
        navigate(`/workspace/${ws}/document/${doc.id}`, {
          state: { citation: { page: c.page_number, text: c.text } },
        });
      } catch {
        showToast("Could not open the cited document");
      }
    },
    [meta, citation, ws, navigate, showToast],
  );

  // ---- search callbacks ------------------------------------------------
  const onSearchActive = useCallback(
    (m: SearchMatch | null) => {
      setActiveSearch(m);
      if (m) canvasRef.current?.scrollToPage(m.page);
    },
    [],
  );
  const onGotoMatch = useCallback(
    (index: number) => {
      const m = searchMatches[index];
      if (m) onSearchActive(m);
    },
    [searchMatches, onSearchActive],
  );
  const searchHitsByPage = useMemo(() => {
    const map = new Map<number, number[]>();
    for (const m of searchMatches) {
      const arr = map.get(m.page) ?? [];
      arr.push(m.itemIndex);
      map.set(m.page, arr);
    }
    return map;
  }, [searchMatches]);

  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    setSearchMatches([]);
    setActiveSearch(null);
  }, []);

  // ---- keyboard shortcuts ---------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setSearchOpen((s) => !s);
        return;
      }
      if (e.key === "Escape") {
        setSelMenu(null);
        setCtxMenu(null);
        if (searchOpen) closeSearch();
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        return;
      }
      if (typing) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        setCurrentPage((p) => {
          const n = Math.min(numPages, p + 1);
          canvasRef.current?.scrollToPage(n);
          return n;
        });
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        setCurrentPage((p) => {
          const n = Math.max(1, p - 1);
          canvasRef.current?.scrollToPage(n);
          return n;
        });
      } else if (e.key === "+" || e.key === "=") {
        zoomIn();
      } else if (e.key === "-") {
        zoomOut();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [numPages, searchOpen, closeSearch, zoomIn, zoomOut]);

  const title = meta?.display_name || meta?.filename || "Document";

  return (
    <div className="pdf-viewer" ref={rootRef}>
      <PdfToolbar
        title={title}
        page={currentPage}
        numPages={numPages}
        onPage={scrollToPage}
        zoomPercent={Math.round(scale * 100)}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onFitWidth={fitWidth}
        onFitPage={fitPage}
        onResetZoom={resetZoom}
        onRotateLeft={rotateLeft}
        onRotateRight={rotateRight}
        searchOpen={searchOpen}
        onToggleSearch={() => (searchOpen ? closeSearch() : setSearchOpen(true))}
        fullscreen={fullscreen}
        onToggleFullscreen={toggleFullscreen}
        onDownload={download}
        onPrint={print}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((s) => !s)}
        aiPanelOpen={aiPanelOpen}
        onToggleAiPanel={() => setAiPanelOpen((s) => !s)}
        onBack={() => navigate(`/workspace/${ws}/library`)}
      />

      {searchOpen && (
        <PdfSearch
          numPages={numPages}
          getPage={getPage}
          onResults={setSearchMatches}
          onActive={onSearchActive}
          onClose={closeSearch}
        />
      )}

      <div className="pdf-progress-bar" aria-hidden="true">
        <div className="pdf-progress-fill" style={{ width: `${progress}%` }} />
      </div>

      <div className="pdf-viewer-body">
        {sidebarOpen && (
          <PdfSidebar
            pdf={pdf}
            numPages={numPages}
            getPage={getPage}
            outline={outline}
            sections={sections}
            searchMatches={searchMatches}
            recentPages={recentPages}
            currentPage={currentPage}
            baseWidth={base?.w ?? 612}
            baseHeight={base?.h ?? 792}
            onGotoPage={scrollToPage}
            onGotoMatch={onGotoMatch}
          />
        )}

        <main
          className="pdf-viewer-main"
          onMouseUp={onViewerMouseUp}
          onContextMenu={onViewerContextMenu}
        >
          {loading && (
            <div className="pdf-viewer-status">
              <span className="ws-brand-mark spin">🧠</span>
              <p>Loading document…</p>
            </div>
          )}
          {error && <div className="pdf-viewer-status ws-error-banner">{error}</div>}
          {!loading && !error && base && (
            <PdfCanvas
              ref={canvasRef}
              numPages={numPages}
              getPage={getPage}
              scale={scale}
              rotation={rotation}
              baseWidth={base.w}
              baseHeight={base.h}
              searchHitsByPage={searchHitsByPage}
              activeSearch={activeSearch}
              citationsByPage={citation.citationsByPage}
              onCurrentPage={setCurrentPage}
              onProgress={onProgress}
            />
          )}
        </main>

        {aiPanelOpen && (
          <AiPanel
            workspaceId={ws}
            pendingAsk={pendingAsk}
            onCitation={handleCitation}
            onClose={() => setAiPanelOpen(false)}
          />
        )}
      </div>

      {selMenu && (
        <SelectionMenu x={selMenu.x} y={selMenu.y} text={selMenu.text} onAction={handleAction} />
      )}
      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          text={ctxMenu.text}
          onAction={handleAction}
          onClose={() => setCtxMenu(null)}
        />
      )}
      {toast && <div className="pdf-toast">{toast}</div>}
    </div>
  );
}
