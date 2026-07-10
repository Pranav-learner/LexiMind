// Reading-progress persistence. On mount it restores the saved page / zoom / rotation (instantly
// from a localStorage cache, then reconciled with the server). On page/zoom/rotation change it
// debounces (~800ms) a PUT to the reading endpoint and writes the localStorage cache. localStorage
// is keyed `leximind_reading_<docId>`.

import { useEffect, useRef } from "react";
import * as viewerApi from "../../api/viewer";

const DEBOUNCE_MS = 800;
const lsKey = (docId: string) => `leximind_reading_${docId}`;

export interface RestoredSession {
  page: number;
  zoom: number; // percent
  rotation: number;
  scrollTop: number;
}

// Synchronous read of the localStorage cache — used to initialize viewer state instantly.
export function readCachedSession(docId: string): RestoredSession | null {
  try {
    const raw = localStorage.getItem(lsKey(docId));
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<RestoredSession>;
    if (typeof p.page !== "number") return null;
    return {
      page: p.page,
      zoom: typeof p.zoom === "number" ? p.zoom : 100,
      rotation: typeof p.rotation === "number" ? p.rotation : 0,
      scrollTop: typeof p.scrollTop === "number" ? p.scrollTop : 0,
    };
  } catch {
    return null;
  }
}

interface Current {
  page: number;
  zoomPercent: number;
  rotation: number;
  scrollTop: number;
}

export function useReadingSession(
  ws: string,
  docId: string,
  current: Current,
  onRestore: (s: RestoredSession) => void,
) {
  const currentRef = useRef(current);
  currentRef.current = current;
  const restoredRef = useRef(false);
  const firstSave = useRef(true);

  // Restore from the server once.
  useEffect(() => {
    let alive = true;
    restoredRef.current = false;
    firstSave.current = true;
    viewerApi
      .getReadingProgress(ws, docId)
      .then((s) => {
        if (!alive || !s || restoredRef.current) return;
        restoredRef.current = true;
        onRestore({
          page: s.page,
          zoom: s.zoom,
          rotation: s.rotation,
          scrollTop: s.scroll_top,
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [ws, docId, onRestore]);

  // Debounced save on discrete state changes; scrollTop is read fresh at save time.
  useEffect(() => {
    if (firstSave.current) {
      firstSave.current = false;
      return;
    }
    const c = currentRef.current;
    const body = {
      page: Math.max(1, c.page),
      scroll_top: Math.round(c.scrollTop),
      zoom: c.zoomPercent,
      rotation: c.rotation,
    };
    try {
      localStorage.setItem(
        lsKey(docId),
        JSON.stringify({
          page: body.page,
          zoom: body.zoom,
          rotation: body.rotation,
          scrollTop: body.scroll_top,
        }),
      );
    } catch {
      /* ignore quota errors */
    }
    const t = setTimeout(() => {
      viewerApi.putReadingProgress(ws, docId, body).catch(() => {});
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [ws, docId, current.page, current.zoomPercent, current.rotation]);
}
