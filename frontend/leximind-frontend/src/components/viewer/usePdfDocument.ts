// Loads a PDF for the viewer: fetches the raw bytes (with the bearer token) + the document
// metadata, hands the ArrayBuffer to pdf.js, and exposes the document proxy, page count,
// outline and a small page cache. The pdf.js document is destroyed on unmount / doc change.

import { useEffect, useRef, useState } from "react";
import * as docApi from "../../api/documents";
import * as viewerApi from "../../api/viewer";
import { pdfjsLib } from "./pdfjs";
import type { PdfDocumentProxy, PdfPageProxy, PdfOutline } from "./pdfjs";
import type { LibraryDocumentDetail } from "../../types";

interface PdfDocumentState {
  pdf: PdfDocumentProxy | null;
  meta: LibraryDocumentDetail | null;
  numPages: number;
  outline: PdfOutline;
  loading: boolean;
  error: string | null;
  getPage: (n: number) => Promise<PdfPageProxy>;
}

export function usePdfDocument(ws: string, docId: string): PdfDocumentState {
  const [pdf, setPdf] = useState<PdfDocumentProxy | null>(null);
  const [meta, setMeta] = useState<LibraryDocumentDetail | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [outline, setOutline] = useState<PdfOutline>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pageCache = useRef<Map<number, Promise<PdfPageProxy>>>(new Map());
  const pdfRef = useRef<PdfDocumentProxy | null>(null);
  const loadingTaskRef = useRef<ReturnType<typeof pdfjsLib.getDocument> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    pageCache.current = new Map();
    setLoading(true);
    setError(null);
    setPdf(null);

    (async () => {
      try {
        const [buffer, metadata] = await Promise.all([
          viewerApi.fetchDocumentFile(ws, docId, controller.signal),
          docApi.getDocument(ws, docId),
        ]);
        if (cancelled) return;
        setMeta(metadata);

        const loadingTask = pdfjsLib.getDocument({ data: new Uint8Array(buffer) });
        loadingTaskRef.current = loadingTask;
        const doc = await loadingTask.promise;
        if (cancelled) {
          loadingTask.destroy();
          return;
        }
        pdfRef.current = doc;
        setPdf(doc);
        setNumPages(doc.numPages);

        try {
          const o = await doc.getOutline();
          if (!cancelled) setOutline(o ?? []);
        } catch {
          if (!cancelled) setOutline([]);
        }
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        setError(err instanceof Error ? err.message : "Failed to load document.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      pageCache.current = new Map();
      pdfRef.current = null;
      const task = loadingTaskRef.current;
      loadingTaskRef.current = null;
      if (task) task.destroy().catch(() => {});
    };
  }, [ws, docId]);

  function getPage(n: number): Promise<PdfPageProxy> {
    const doc = pdfRef.current;
    if (!doc) return Promise.reject(new Error("PDF not loaded"));
    const cached = pageCache.current.get(n);
    if (cached) return cached;
    const p = doc.getPage(n);
    pageCache.current.set(n, p);
    return p;
  }

  return { pdf, meta, numPages, outline, loading, error, getPage };
}
