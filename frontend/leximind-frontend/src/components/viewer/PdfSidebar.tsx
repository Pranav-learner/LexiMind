// Left sidebar with tabbed navigation: Thumbnails (lazy low-scale canvases), Outline (pdf.js
// bookmarks with a /chunks section-list fallback), Search results, Recent pages, plus placeholder
// tabs for future Bookmarks / Notes / Annotations modules. Every entry navigates to a page.

import { memo, useEffect, useRef, useState } from "react";
import type { PdfDocumentProxy, PdfPageProxy, PdfOutlineNode } from "./pdfjs";
import type { SearchMatch } from "./PdfSearch";

type Tab = "thumbnails" | "outline" | "search" | "recent" | "bookmarks" | "notes" | "annotations";

export interface SectionEntry {
  section: string;
  page: number;
}

interface Props {
  pdf: PdfDocumentProxy | null;
  numPages: number;
  getPage: (n: number) => Promise<PdfPageProxy>;
  outline: PdfOutlineNode[];
  sections: SectionEntry[];
  searchMatches: SearchMatch[];
  recentPages: number[];
  currentPage: number;
  baseWidth: number;
  baseHeight: number;
  onGotoPage: (n: number) => void;
  onGotoMatch: (index: number) => void;
}

const TABS: { id: Tab; icon: string; label: string; live: boolean }[] = [
  { id: "thumbnails", icon: "🖼", label: "Thumbnails", live: true },
  { id: "outline", icon: "☰", label: "Outline", live: true },
  { id: "search", icon: "🔍", label: "Search", live: true },
  { id: "recent", icon: "🕑", label: "Recent", live: true },
  { id: "bookmarks", icon: "🔖", label: "Bookmarks", live: false },
  { id: "notes", icon: "📝", label: "Notes", live: false },
  { id: "annotations", icon: "✍", label: "Annotations", live: false },
];

// Resolve a pdf.js outline destination to a 1-based page number.
async function destToPage(
  pdf: PdfDocumentProxy,
  dest: string | unknown[] | null,
): Promise<number | null> {
  try {
    const explicit = typeof dest === "string" ? await pdf.getDestination(dest) : dest;
    if (!Array.isArray(explicit) || !explicit.length) return null;
    const ref = explicit[0];
    if (ref && typeof ref === "object") {
      const idx = await pdf.getPageIndex(ref as Parameters<PdfDocumentProxy["getPageIndex"]>[0]);
      return idx + 1;
    }
    if (typeof ref === "number") return ref + 1;
  } catch {
    /* ignore */
  }
  return null;
}

function OutlineNode({
  node,
  pdf,
  depth,
  onGotoPage,
}: {
  node: PdfOutlineNode;
  pdf: PdfDocumentProxy;
  depth: number;
  onGotoPage: (n: number) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const children = (node.items ?? []) as PdfOutlineNode[];
  return (
    <li className="pdf-outline-node">
      <div className="pdf-outline-row" style={{ paddingLeft: `${depth * 12}px` }}>
        {children.length > 0 ? (
          <button className="pdf-outline-toggle" aria-label={open ? "Collapse" : "Expand"} onClick={() => setOpen((o) => !o)}>
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="pdf-outline-toggle" />
        )}
        <button
          className="pdf-outline-link"
          onClick={async () => {
            const p = await destToPage(pdf, node.dest);
            if (p) onGotoPage(p);
          }}
        >
          {node.title}
        </button>
      </div>
      {open && children.length > 0 && (
        <ul className="pdf-outline-list">
          {children.map((c, i) => (
            <OutlineNode key={i} node={c} pdf={pdf} depth={depth + 1} onGotoPage={onGotoPage} />
          ))}
        </ul>
      )}
    </li>
  );
}

function ThumbnailBase({
  pageNumber,
  getPage,
  scrollRoot,
  active,
  aspect,
  onGoto,
}: {
  pageNumber: number;
  getPage: (n: number) => Promise<PdfPageProxy>;
  scrollRoot: HTMLElement | null;
  active: boolean;
  aspect: number;
  onGoto: (n: number) => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setVisible(true)),
      { root: scrollRoot ?? null, rootMargin: "200% 0px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [scrollRoot]);

  useEffect(() => {
    if (!visible || done) return;
    let cancelled = false;
    (async () => {
      try {
        const page = await getPage(pageNumber);
        if (cancelled) return;
        const viewport = page.getViewport({ scale: 0.25 });
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext("2d");
        if (!canvas || !ctx) return;
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        await page.render({ canvas, canvasContext: ctx, viewport }).promise;
        if (!cancelled) setDone(true);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible, done, getPage, pageNumber]);

  return (
    <button
      ref={ref}
      className={`pdf-thumb ${active ? "active" : ""}`}
      onClick={() => onGoto(pageNumber)}
      title={`Page ${pageNumber}`}
    >
      <div className="pdf-thumb-canvas-wrap" style={{ aspectRatio: String(aspect) }}>
        <canvas ref={canvasRef} className="pdf-thumb-canvas" />
        {!done && <span className="pdf-thumb-spinner" />}
      </div>
      <span className="pdf-thumb-label">{pageNumber}</span>
    </button>
  );
}
const Thumbnail = memo(ThumbnailBase);

function PdfSidebar({
  pdf,
  numPages,
  getPage,
  outline,
  sections,
  searchMatches,
  recentPages,
  currentPage,
  baseWidth,
  baseHeight,
  onGotoPage,
  onGotoMatch,
}: Props) {
  const [tab, setTab] = useState<Tab>("thumbnails");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollRoot, setScrollRoot] = useState<HTMLElement | null>(null);
  const aspect = baseWidth / baseHeight || 0.7727;

  // Keep the active thumbnail in view when the current page changes.
  useEffect(() => {
    if (tab !== "thumbnails") return;
    const root = scrollRef.current;
    const el = root?.querySelector<HTMLElement>(`.pdf-thumb.active`);
    el?.scrollIntoView({ block: "nearest" });
  }, [currentPage, tab]);

  return (
    <aside className="pdf-sidebar" aria-label="Document navigation">
      <div className="pdf-sidebar-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`pdf-sidebar-tab ${tab === t.id ? "active" : ""}`}
            title={t.live ? t.label : `${t.label} (coming soon)`}
            onClick={() => setTab(t.id)}
          >
            <span aria-hidden="true">{t.icon}</span>
          </button>
        ))}
      </div>

      <div
        className="pdf-sidebar-body"
        ref={(el) => {
          scrollRef.current = el;
          setScrollRoot(el);
        }}
      >
        {tab === "thumbnails" && (
          <div className="pdf-thumbs">
            {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
              <Thumbnail
                key={n}
                pageNumber={n}
                getPage={getPage}
                scrollRoot={scrollRoot}
                active={n === currentPage}
                aspect={aspect}
                onGoto={onGotoPage}
              />
            ))}
          </div>
        )}

        {tab === "outline" && (
          <div className="pdf-outline">
            {pdf && outline.length > 0 ? (
              <ul className="pdf-outline-list">
                {outline.map((node, i) => (
                  <OutlineNode key={i} node={node} pdf={pdf} depth={0} onGotoPage={onGotoPage} />
                ))}
              </ul>
            ) : sections.length > 0 ? (
              <ul className="pdf-section-list">
                {sections.map((s, i) => (
                  <li key={i}>
                    <button className="pdf-section-link" onClick={() => onGotoPage(s.page)}>
                      <span className="pdf-section-name">{s.section}</span>
                      <span className="pdf-section-page">p.{s.page}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="doc-muted pdf-sidebar-empty">No outline available.</p>
            )}
          </div>
        )}

        {tab === "search" && (
          <div className="pdf-search-results">
            {searchMatches.length ? (
              <ul>
                {searchMatches.map((m, i) => (
                  <li key={i}>
                    <button className="pdf-search-result" onClick={() => onGotoMatch(i)}>
                      <span className="pdf-search-result-idx">#{i + 1}</span>
                      <span className="pdf-search-result-page">Page {m.page}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="doc-muted pdf-sidebar-empty">
                Open search (🔍) and type to see matches here.
              </p>
            )}
          </div>
        )}

        {tab === "recent" && (
          <div className="pdf-recent">
            {recentPages.length ? (
              <ul>
                {recentPages.map((p, i) => (
                  <li key={i}>
                    <button className="pdf-recent-item" onClick={() => onGotoPage(p)}>
                      Page {p}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="doc-muted pdf-sidebar-empty">Pages you visit will appear here.</p>
            )}
          </div>
        )}

        {(tab === "bookmarks" || tab === "notes" || tab === "annotations") && (
          <div className="pdf-sidebar-placeholder">
            <p className="doc-muted">
              {tab === "bookmarks" ? "🔖 Bookmarks" : tab === "notes" ? "📝 Notes" : "✍ Annotations"}
            </p>
            <p className="doc-muted">Coming soon.</p>
          </div>
        )}
      </div>
    </aside>
  );
}

export default PdfSidebar;
