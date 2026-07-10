// Renders ONE PDF page: a <canvas> (raster) plus an absolutely-positioned text layer used for
// selection / search / highlight. Virtualized — it only renders when its wrapper is near the
// scroll viewport (IntersectionObserver) and tears the canvas down when it scrolls away, so a
// 1000-page document never holds 1000 canvases in memory. Memoized to avoid needless re-renders.

import { memo, useEffect, useRef, useState } from "react";
import { pdfjsLib } from "./pdfjs";
import type { PdfPageProxy } from "./pdfjs";
import { applyHighlights } from "./highlight";
import type { RenderTask } from "pdfjs-dist";

interface Props {
  pageNumber: number;
  getPage: (n: number) => Promise<PdfPageProxy>;
  scale: number;
  rotation: number;
  // Unscaled page dims used to size the placeholder before the real page renders.
  baseWidth: number;
  baseHeight: number;
  scrollRoot: HTMLElement | null;
  searchHits: number[];
  activeSearchHit: number | null;
  citationSnippets: string[];
  onRegister: (n: number, el: HTMLElement | null) => void;
}

const DPR = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2);

function PdfPageBase({
  pageNumber,
  getPage,
  scale,
  rotation,
  baseWidth,
  baseHeight,
  scrollRoot,
  searchHits,
  activeSearchHit,
  citationSnippets,
  onRegister,
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);

  const renderTaskRef = useRef<RenderTask | null>(null);
  const textLayerInstanceRef = useRef<{ cancel: () => void } | null>(null);
  const textDivsRef = useRef<HTMLElement[]>([]);
  const itemStringsRef = useRef<string[]>([]);

  const [visible, setVisible] = useState(false);
  const [rendered, setRendered] = useState(false);

  // Placeholder / wrapper size. Swap width/height for 90/270deg rotations.
  const rotated = rotation % 180 !== 0;
  const w = (rotated ? baseHeight : baseWidth) * scale;
  const h = (rotated ? baseWidth : baseHeight) * scale;

  // Register the wrapper element with the parent so it can scroll this page into view.
  useEffect(() => {
    onRegister(pageNumber, wrapperRef.current);
    return () => onRegister(pageNumber, null);
  }, [pageNumber, onRegister]);

  // Virtualization: render only when near the viewport.
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) setVisible(entry.isIntersecting);
      },
      { root: scrollRoot ?? null, rootMargin: "150% 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [scrollRoot]);

  // Render canvas + text layer when visible / on scale / rotation change.
  useEffect(() => {
    if (!visible) {
      // Tear down to free memory when scrolled away.
      renderTaskRef.current?.cancel();
      renderTaskRef.current = null;
      textLayerInstanceRef.current?.cancel();
      textLayerInstanceRef.current = null;
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = 0;
        canvas.height = 0;
      }
      if (textLayerRef.current) textLayerRef.current.replaceChildren();
      textDivsRef.current = [];
      itemStringsRef.current = [];
      setRendered(false);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const page = await getPage(pageNumber);
        if (cancelled) return;
        const viewport = page.getViewport({ scale, rotation });

        const wrapper = wrapperRef.current;
        if (wrapper) wrapper.style.setProperty("--total-scale-factor", String(scale));

        const canvas = canvasRef.current;
        const ctx = canvas?.getContext("2d");
        if (!canvas || !ctx) return;
        canvas.width = Math.floor(viewport.width * DPR);
        canvas.height = Math.floor(viewport.height * DPR);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        renderTaskRef.current?.cancel();
        const task = page.render({
          canvas,
          canvasContext: ctx,
          viewport,
          transform: DPR !== 1 ? [DPR, 0, 0, DPR, 0, 0] : undefined,
        });
        renderTaskRef.current = task;
        await task.promise;
        if (cancelled) return;

        // Text layer.
        const textContent = await page.getTextContent();
        if (cancelled) return;
        const container = textLayerRef.current;
        if (!container) return;
        container.replaceChildren();
        textLayerInstanceRef.current?.cancel();
        const textLayer = new pdfjsLib.TextLayer({
          textContentSource: textContent,
          container,
          viewport,
        });
        textLayerInstanceRef.current = textLayer;
        await textLayer.render();
        if (cancelled) return;
        textDivsRef.current = textLayer.textDivs as HTMLElement[];
        itemStringsRef.current = textLayer.textContentItemsStr;
        setRendered(true);
      } catch (err) {
        if (
          !cancelled &&
          !(err instanceof Error && err.name === "RenderingCancelledException")
        ) {
          // Silently ignore cancellations; log genuine render errors.
          console.error(`Failed to render page ${pageNumber}`, err);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [visible, scale, rotation, pageNumber, getPage]);

  // (Re)apply highlights whenever the page is rendered or the highlight spec changes.
  useEffect(() => {
    if (!rendered) return;
    const first = applyHighlights(textDivsRef.current, itemStringsRef.current, {
      searchHits,
      activeSearchHit,
      citationSnippets,
    });
    if (activeSearchHit != null) {
      textDivsRef.current[activeSearchHit]?.scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
    } else if (first) {
      first.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [rendered, searchHits, activeSearchHit, citationSnippets]);

  // Final cleanup on unmount.
  useEffect(() => {
    return () => {
      renderTaskRef.current?.cancel();
      textLayerInstanceRef.current?.cancel();
    };
  }, []);

  return (
    <div
      ref={wrapperRef}
      className="pdf-page"
      data-page={pageNumber}
      style={{ width: `${w}px`, height: `${h}px` }}
    >
      <canvas ref={canvasRef} className="pdf-page-canvas" />
      <div ref={textLayerRef} className="textLayer" />
      {!rendered && <div className="pdf-page-placeholder">Page {pageNumber}</div>}
    </div>
  );
}

export default memo(PdfPageBase);
