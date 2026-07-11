"""Cross-modal citation manager (Step 9) — every modality stays traceable to a viewer target.

Extends Phase-2 citations to text/OCR/diagram/image/chart/table/metadata. Each included evidence item
yields a citation carrying `document_id` + `page_number` (→ open the PDF at the page, reusing Module 3)
and, for visual evidence, the `asset_id` (→ the extracted asset). Citations are deduplicated by their
(document, page, asset) target so the same source isn't listed twice, while every merged source (from
cross-modal dedup) is still represented.
"""

from __future__ import annotations

from typing import List

from app.mmcontext.schemas import ContextBlock, MMCitation


def collect(blocks: List[ContextBlock]) -> List[MMCitation]:
    seen = set()
    out: List[MMCitation] = []
    for block in blocks:
        for ev in block.items:
            c = ev.citation()
            key = (c.document_id, c.page_number, c.asset_id, c.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
    return out
