// Orchestrates citation highlighting: navigate to a page, scroll it into view, and highlight the
// referenced snippet on that page's text layer. Supports MULTIPLE simultaneous citations and two
// clearing modes — auto-clear after a timeout (default ~6s) OR stay until explicitly cleared
// (toggle `persistent`). The actual span matching happens in PdfPage via `citationsByPage`.

import { useCallback, useRef, useState } from "react";

interface Options {
  scrollToPage: (page: number) => void;
  timeoutMs?: number;
}

export interface CitationTarget {
  page: number;
  text: string;
}

export function useCitationHighlight({ scrollToPage, timeoutMs = 6000 }: Options) {
  const [citationsByPage, setCitationsByPage] = useState<Map<number, string[]>>(new Map());
  const [persistent, setPersistent] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistentRef = useRef(persistent);
  persistentRef.current = persistent;

  const clear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    setCitationsByPage(new Map());
  }, []);

  const scheduleClear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (persistentRef.current) return;
    timerRef.current = setTimeout(() => setCitationsByPage(new Map()), timeoutMs);
  }, [timeoutMs]);

  // Highlight one or more citation targets, navigating to the first one's page.
  const highlight = useCallback(
    (targets: CitationTarget | CitationTarget[]) => {
      const list = Array.isArray(targets) ? targets : [targets];
      if (!list.length) return;
      const map = new Map<number, string[]>();
      for (const t of list) {
        const arr = map.get(t.page) ?? [];
        arr.push(t.text);
        map.set(t.page, arr);
      }
      setCitationsByPage(map);
      scrollToPage(list[0].page);
      scheduleClear();
    },
    [scrollToPage, scheduleClear],
  );

  return { citationsByPage, highlight, clear, persistent, setPersistent };
}
