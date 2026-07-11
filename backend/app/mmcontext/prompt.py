"""Multimodal prompt builder (Step 8) — a deterministic, inspectable structured prompt.

Layout: System Instructions → Question → per-modality evidence sections (each item tagged with a
`[n]` citation marker) → a Citation block mapping every `[n]` to its source → the User Question. The
block ORDER comes from adaptive assembly, so different query types yield different prompts. Everything
is deterministic (no randomness) and easy to diff/inspect (developer mode returns the raw string).
"""

from __future__ import annotations

from typing import List, Tuple

from app.mmcontext.schemas import ContextBlock

SYSTEM_PROMPT = """You are LexiMind, a precise multimodal research assistant.

Answer the user's question using ONLY the evidence provided below, which may include text, OCR'd
scans, image/diagram/chart descriptions, and tables. When you use a piece of evidence, cite it with
its [n] marker. Visual evidence (diagrams, charts, tables) is as authoritative as text — reason over
it directly. If the evidence does not contain the answer, say you don't know based on the provided
sources. Be concise and ground every claim in a citation."""


def _citation_label(cit) -> str:
    parts = [cit.modality]
    if cit.source_type and cit.source_type != cit.modality:
        parts.append(cit.source_type)
    if cit.page_number is not None:
        parts.append(f"p.{cit.page_number}")
    if cit.asset_id:
        parts.append(f"asset {cit.asset_id[:10]}")
    return " · ".join(parts)


def build(query: str, blocks: List[ContextBlock]) -> Tuple[str, str, List[dict]]:
    """Return (full_prompt, context_only, citation_index) with `[n]` markers assigned in block order."""
    n = 0
    context_lines: List[str] = []
    citation_index: List[dict] = []

    for block in blocks:
        if not block.items:
            continue
        context_lines.append(f"### {block.header}")
        for ev in block.items:
            n += 1
            context_lines.append(f"[{n}] {ev.content}")
            cit = ev.citation()
            citation_index.append({
                "index": n, "modality": cit.modality, "source_type": cit.source_type,
                "document_id": cit.document_id, "chunk_id": cit.chunk_id, "asset_id": cit.asset_id,
                "page_number": cit.page_number, "label": _citation_label(cit),
            })
        context_lines.append("")

    context_text = "\n".join(context_lines).strip()

    citation_lines = ["Citations:"]
    for c in citation_index:
        citation_lines.append(f"[{c['index']}] {c['label']}")
    citation_block = "\n".join(citation_lines) if citation_index else "Citations: (none)"

    full_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Question:\n{query}\n\n"
        f"Evidence:\n{context_text or '(no evidence found)'}\n\n"
        f"{citation_block}\n\n"
        f"Answer the question above, citing evidence with [n] markers.\n\n"
        f"User question: {query}\n\nAnswer:"
    )
    return full_prompt, context_text, citation_index
