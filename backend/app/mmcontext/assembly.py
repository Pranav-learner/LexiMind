"""Adaptive context assembly (Step 7) — order the context blocks by query intent, not a fixed layout.

The primary intent modality leads (an architecture question puts diagrams first; a definition puts
text first), then the remaining modalities follow by their intent weight, with text always kept high
as the backbone. Each modality becomes a labelled `ContextBlock` with its included evidence ordered by
rank. Different query types therefore produce different layouts — the core adaptive behaviour.
"""

from __future__ import annotations

from typing import Dict, List

from app.mmcontext.schemas import ContextBlock, MMEvidence

_HEADERS = {
    "text": "Relevant text", "ocr": "Scanned / OCR text", "image": "Relevant images",
    "diagram": "Relevant diagrams", "table": "Relevant tables", "metadata": "Document metadata",
}


def assemble(included: List[MMEvidence], modality_weights: Dict[str, float], primary: str) -> List[ContextBlock]:
    by_modality: Dict[str, List[MMEvidence]] = {}
    for ev in included:
        by_modality.setdefault(ev.modality, []).append(ev)

    present = list(by_modality.keys())

    def order_key(m: str):
        # primary first (0), then by descending intent weight; text gets a small backbone boost.
        primary_rank = 0 if m == primary else 1
        boost = 0.1 if m == "text" else 0.0
        return (primary_rank, -(modality_weights.get(m, 0.5) + boost))

    ordered = sorted(present, key=order_key)
    blocks: List[ContextBlock] = []
    for i, m in enumerate(ordered):
        items = sorted(by_modality[m], key=lambda e: e.rank)
        blocks.append(ContextBlock(modality=m, header=_HEADERS.get(m, m.title()),
                                   items=items, token_cost=sum(e.token_cost for e in items), order=i))
    return blocks
