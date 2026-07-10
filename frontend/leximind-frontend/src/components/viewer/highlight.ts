// Shared text-layer highlight helpers. Both citation highlighting and full-text search operate
// on the pdf.js text-layer <span> divs (one per text item). We match by item index (search) or
// by snippet containment (citations) and toggle CSS classes — no DOM surgery, so re-render of
// the text layer naturally clears everything.

const SEARCH_HIT = "pdf-search-hit";
const SEARCH_HIT_ACTIVE = "pdf-search-hit-active";
const CITATION = "pdf-highlight";

// Collapse whitespace + lowercase so snippet matching is resilient to line-wrap differences.
export function normalizeText(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

export interface HighlightSpec {
  searchHits: number[]; // text-item indices on this page that match the query
  activeSearchHit: number | null; // the item index that is the current match (this page only)
  citationSnippets: string[]; // full citation texts to highlight on this page
}

export function clearHighlights(divs: HTMLElement[]): void {
  for (const d of divs) {
    d.classList.remove(SEARCH_HIT, SEARCH_HIT_ACTIVE, CITATION);
  }
}

// Returns the first element that received a citation highlight (for scroll-into-view).
export function applyHighlights(
  divs: HTMLElement[],
  itemStrings: string[],
  spec: HighlightSpec,
): HTMLElement | null {
  clearHighlights(divs);

  for (const idx of spec.searchHits) {
    divs[idx]?.classList.add(SEARCH_HIT);
  }
  if (spec.activeSearchHit != null) {
    divs[spec.activeSearchHit]?.classList.add(SEARCH_HIT_ACTIVE);
  }

  let firstCitation: HTMLElement | null = null;
  if (spec.citationSnippets.length) {
    const normSnippets = spec.citationSnippets.map(normalizeText).filter(Boolean);
    divs.forEach((div, i) => {
      const s = normalizeText(itemStrings[i] ?? "");
      if (s.length < 2) return;
      if (normSnippets.some((snip) => snip.includes(s))) {
        div.classList.add(CITATION);
        if (!firstCitation) firstCitation = div;
      }
    });
  }
  return firstCitation;
}
