// Full-text search across the whole PDF. Scans each page's text content lazily/incrementally
// (cached per page) so it stays responsive on very large documents — results stream in and the
// UI never blocks. Reports the flat match list + the active match up to the parent, which drives
// the text-layer highlighting. Enter / ▼ = next match, ▲ = previous, with an "n of m" counter.

import { useCallback, useEffect, useRef, useState } from "react";
import type { PdfPageProxy } from "./pdfjs";

export interface SearchMatch {
  page: number;
  itemIndex: number;
}

interface Props {
  numPages: number;
  getPage: (n: number) => Promise<PdfPageProxy>;
  onResults: (matches: SearchMatch[]) => void;
  onActive: (match: SearchMatch | null) => void;
  onClose: () => void;
}

export default function PdfSearch({
  numPages,
  getPage,
  onResults,
  onActive,
  onClose,
}: Props) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [current, setCurrent] = useState(0);
  const [searching, setSearching] = useState(false);

  const textCache = useRef<Map<number, string[]>>(new Map());
  const runToken = useRef(0);

  // Debounced incremental scan on query change.
  useEffect(() => {
    const q = query.trim().toLowerCase();
    const token = ++runToken.current;
    if (!q) {
      setMatches([]);
      setSearching(false);
      onResults([]);
      onActive(null);
      return;
    }

    const handle = setTimeout(async () => {
      setSearching(true);
      const found: SearchMatch[] = [];
      let firstReported = false;
      for (let p = 1; p <= numPages; p++) {
        if (runToken.current !== token) return; // superseded
        let strings = textCache.current.get(p);
        if (!strings) {
          try {
            const page = await getPage(p);
            const tc = await page.getTextContent();
            strings = tc.items.map((it) => ("str" in it ? it.str : ""));
            textCache.current.set(p, strings);
          } catch {
            strings = [];
          }
        }
        if (runToken.current !== token) return;
        strings.forEach((s, i) => {
          if (s.toLowerCase().includes(q)) found.push({ page: p, itemIndex: i });
        });
        // Stream partial results so the counter/highlights appear progressively.
        if (found.length && (!firstReported || p % 10 === 0)) {
          firstReported = true;
          setMatches([...found]);
          onResults([...found]);
        }
      }
      if (runToken.current !== token) return;
      setMatches(found);
      onResults(found);
      setSearching(false);
      if (found.length) {
        setCurrent(0);
        onActive(found[0]);
      } else {
        onActive(null);
      }
    }, 250);

    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, numPages]);

  const go = useCallback(
    (dir: 1 | -1) => {
      if (!matches.length) return;
      setCurrent((c) => {
        const next = (c + dir + matches.length) % matches.length;
        onActive(matches[next]);
        return next;
      });
    },
    [matches, onActive],
  );

  // Focus the input when mounted.
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <div className="pdf-search">
      <input
        ref={inputRef}
        className="pdf-search-input"
        placeholder="Search document…"
        value={query}
        aria-label="Search document"
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            go(e.shiftKey ? -1 : 1);
          } else if (e.key === "Escape") {
            onClose();
          }
        }}
      />
      <span className="pdf-search-count">
        {searching && !matches.length
          ? "Searching…"
          : matches.length
            ? `${current + 1} of ${matches.length}${searching ? "…" : ""}`
            : query.trim()
              ? "No matches"
              : ""}
      </span>
      <button className="ws-icon-btn" title="Previous match" aria-label="Previous match" disabled={!matches.length} onClick={() => go(-1)}>▲</button>
      <button className="ws-icon-btn" title="Next match" aria-label="Next match" disabled={!matches.length} onClick={() => go(1)}>▼</button>
      <button className="ws-icon-btn" title="Close search" aria-label="Close search" onClick={onClose}>✕</button>
    </div>
  );
}
