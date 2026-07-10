// The scroll container for continuous-scroll mode. Lays out every page (as a virtualized,
// self-sizing PdfPage) in a single scroll column, tracks the current page from scroll position
// via an IntersectionObserver, and reports reading progress. Exposes an imperative handle so the
// parent can scroll to a page or restore a saved scroll offset.

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import PdfPage from "./PdfPage";
import type { PdfPageProxy } from "./pdfjs";

const EMPTY_NUM: number[] = [];
const EMPTY_STR: string[] = [];

export interface PdfCanvasHandle {
  scrollToPage: (n: number, smooth?: boolean) => void;
  scrollTo: (top: number) => void;
  getScrollTop: () => number;
  getViewport: () => { width: number; height: number };
}

interface Props {
  numPages: number;
  getPage: (n: number) => Promise<PdfPageProxy>;
  scale: number;
  rotation: number;
  baseWidth: number;
  baseHeight: number;
  searchHitsByPage: Map<number, number[]>;
  activeSearch: { page: number; itemIndex: number } | null;
  citationsByPage: Map<number, string[]>;
  onCurrentPage: (page: number) => void;
  onProgress: (scrollTop: number, percent: number) => void;
}

const PdfCanvas = forwardRef<PdfCanvasHandle, Props>(function PdfCanvas(
  {
    numPages,
    getPage,
    scale,
    rotation,
    baseWidth,
    baseHeight,
    searchHitsByPage,
    activeSearch,
    citationsByPage,
    onCurrentPage,
    onProgress,
  },
  ref,
) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [root, setRoot] = useState<HTMLElement | null>(null);
  const pageEls = useRef<Map<number, HTMLElement>>(new Map());
  const ratios = useRef<Map<number, number>>(new Map());
  const currentPageRef = useRef(1);

  const setRootRef = useCallback((el: HTMLDivElement | null) => {
    rootRef.current = el;
    setRoot(el);
  }, []);

  const onRegister = useCallback((n: number, el: HTMLElement | null) => {
    if (el) pageEls.current.set(n, el);
    else pageEls.current.delete(n);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      scrollToPage: (n, smooth = true) => {
        const el = pageEls.current.get(n);
        const container = rootRef.current;
        if (el && container) {
          container.scrollTo({
            top: el.offsetTop - 16,
            behavior: smooth ? "smooth" : "auto",
          });
        }
      },
      scrollTo: (top) => rootRef.current?.scrollTo({ top, behavior: "auto" }),
      getScrollTop: () => rootRef.current?.scrollTop ?? 0,
      getViewport: () => ({
        width: rootRef.current?.clientWidth ?? 0,
        height: rootRef.current?.clientHeight ?? 0,
      }),
    }),
    [],
  );

  // Track current page via intersection ratios; report progress on scroll.
  useEffect(() => {
    const container = rootRef.current;
    if (!container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const n = Number((e.target as HTMLElement).dataset.page);
          if (e.isIntersecting) ratios.current.set(n, e.intersectionRatio);
          else ratios.current.delete(n);
        }
        let best = currentPageRef.current;
        let bestRatio = -1;
        for (const [n, r] of ratios.current) {
          if (r > bestRatio || (r === bestRatio && n < best)) {
            bestRatio = r;
            best = n;
          }
        }
        if (best !== currentPageRef.current) {
          currentPageRef.current = best;
          onCurrentPage(best);
        }
      },
      { root: container, threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    for (const el of pageEls.current.values()) observer.observe(el);

    const onScroll = () => {
      const max = container.scrollHeight - container.clientHeight;
      const pct = max > 0 ? Math.min(100, (container.scrollTop / max) * 100) : 0;
      onProgress(container.scrollTop, pct);
    };
    container.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      observer.disconnect();
      container.removeEventListener("scroll", onScroll);
    };
    // Re-observe when page count or layout scale changes (new page elements).
  }, [numPages, scale, rotation, onCurrentPage, onProgress]);

  const pages = [];
  for (let n = 1; n <= numPages; n++) {
    pages.push(
      <PdfPage
        key={n}
        pageNumber={n}
        getPage={getPage}
        scale={scale}
        rotation={rotation}
        baseWidth={baseWidth}
        baseHeight={baseHeight}
        scrollRoot={root}
        searchHits={searchHitsByPage.get(n) ?? EMPTY_NUM}
        activeSearchHit={activeSearch && activeSearch.page === n ? activeSearch.itemIndex : null}
        citationSnippets={citationsByPage.get(n) ?? EMPTY_STR}
        onRegister={onRegister}
      />,
    );
  }

  return (
    <div className="pdf-canvas" ref={setRootRef}>
      <div className="pdf-canvas-inner">{pages}</div>
    </div>
  );
});

export default PdfCanvas;
