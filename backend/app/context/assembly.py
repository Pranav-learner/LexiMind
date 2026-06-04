"""Context assembly (Phase 2, Task 7).

Turns the final, budgeted, compressed evidence into one LLM-ready string. Goals:
  - Group related evidence (same document together) so the LLM sees coherent context.
  - Preserve logical flow within a document (page, then paragraph order).
  - Order groups by relevance (strongest evidence first) so the most useful context leads.
  - Attach an inline, numbered citation marker [n] to every block so the model can cite,
    and return a parallel citation list the API/UI can render.

The output format is deliberately compact and explicit — every block self-identifies its
source, which both grounds the model and makes citations auditable.
"""

from __future__ import annotations

from typing import List, Tuple

from app.context.schemas import Citation, Evidence


def _citation_label(c: Citation) -> str:
    parts = [c.source or "unknown"]
    if c.page_number is not None:
        parts.append(f"Page {c.page_number}")
    if c.section:
        parts.append(c.section)
    return " · ".join(parts)


class ContextAssembler:
    def assemble(self, evidence: List[Evidence]) -> Tuple[str, List[Citation]]:
        if not evidence:
            return "", []

        # Group by document, remembering each group's best evidence score and first-seen
        # order (so ungrouped/None-document evidence still orders sensibly).
        groups: dict = {}
        order: List[str] = []
        for ev in evidence:
            key = ev.document_id or f"__{ev.chunk_id}"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(ev)

        def group_score(key: str) -> float:
            return max(e.evidence_score for e in groups[key])

        # Strongest groups first.
        order.sort(key=group_score, reverse=True)

        blocks: List[str] = []
        citations: List[Citation] = []
        n = 0
        for key in order:
            members = groups[key]
            # Logical flow within a document: by page, then paragraph.
            members.sort(key=lambda e: (
                e.page_number if e.page_number is not None else 1_000_000,
                e.start_paragraph if e.start_paragraph is not None else 1_000_000,
            ))
            for ev in members:
                n += 1
                primary = ev.citations[0]
                label = _citation_label(primary)
                # If this evidence merged several chunks, note the extra citations too.
                if len(ev.citations) > 1:
                    extra = ", ".join(_citation_label(c) for c in ev.citations[1:])
                    label = f"{label} (+ {extra})"
                blocks.append(f"[{n}] {label}\n{ev.text}")
                citations.append(primary)

        return "\n\n".join(blocks), citations
