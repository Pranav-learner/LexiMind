"""Multimodal chunk generation — extends chunking to text/ocr/image/table/figure chunks.

DESIGN NOTE: the existing Phase-1 text chunker (`app.services.chunking_service.chunk_text`) uses
sentence-transformer embeddings for *semantic* paragraph grouping — heavy (torch) and it stays the
sole path for the FAISS-indexed text pipeline (untouched here → backward compatible). Multimodal
chunks are NOT embedded in this module (they sit in the future embedding queue), so this builder uses
a lightweight, dependency-free word-window splitter on the SAME 250-word budget. When multimodal
embeddings land, this and the semantic chunker can be unified behind one interface.

Pure functions only (no I/O, no ORM) → fully unit-testable without OCR/vision libs.
"""

from __future__ import annotations

from typing import Any, Dict, List

MAX_WORDS = 250  # same budget as the text chunker, for consistency


def _split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in (text or "").replace("\r\n", "\n").split("\n\n") if p.strip()]


def _window(paragraphs: List[str]) -> List[str]:
    """Group paragraphs into ~MAX_WORDS windows (greedy, order-preserving)."""
    chunks: List[str] = []
    buf: List[str] = []
    words = 0
    for para in paragraphs:
        pw = len(para.split())
        if words + pw > MAX_WORDS and buf:
            chunks.append("\n\n".join(buf))
            buf, words = [], 0
        buf.append(para)
        words += pw
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _table_to_text(headers, cells) -> str:
    lines = []
    if headers:
        lines.append(" | ".join(str(h) for h in headers))
    for row in (cells or [])[:50]:
        lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)


def build_multimodal_chunks(
    *,
    ocr_pages: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    figures: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Turn extracted assets + per-page text into unified multimodal chunk dicts.

    Each returned dict: {page_number, chunk_type, source, chunk_index, content, bbox, asset_id, meta}.
    `chunk_index` is a global running order. Image/table/figure chunks carry a searchable text
    descriptor (caption or a serialization) so future retrieval has something to embed.
    """
    out: List[Dict[str, Any]] = []
    idx = 0

    # --- text / OCR chunks (per page) ---
    for page in sorted(ocr_pages, key=lambda p: p.get("page_number", 0)):
        source = "ocr" if page.get("from_ocr", True) else "native"
        ctype = "ocr" if source == "ocr" else "text"
        for text in _window(_split_paragraphs(page.get("text", ""))):
            out.append({
                "page_number": page.get("page_number", 0), "chunk_type": ctype, "source": source,
                "chunk_index": idx, "content": text, "bbox": None, "asset_id": None,
                "meta": {"language": page.get("language", ""), "confidence": page.get("confidence")},
            })
            idx += 1

    # --- table chunks ---
    for t in tables:
        descriptor = _table_to_text(t.get("headers"), t.get("cells"))
        caption = t.get("caption") or ""
        content = (f"{caption}\n{descriptor}" if caption else descriptor) or f"[Table on page {t.get('page_number', 0)}]"
        out.append({
            "page_number": t.get("page_number", 0), "chunk_type": "table", "source": "extractor",
            "chunk_index": idx, "content": content.strip(), "bbox": t.get("bbox"),
            "asset_id": t.get("asset_id"),
            "meta": {"n_rows": t.get("n_rows", 0), "n_cols": t.get("n_cols", 0), "caption": caption},
        })
        idx += 1

    # --- figure chunks ---
    for f in figures:
        caption = f.get("caption") or ""
        content = caption or f"[{f.get('figure_type', 'figure').title()} on page {f.get('page_number', 0)}]"
        out.append({
            "page_number": f.get("page_number", 0), "chunk_type": "figure", "source": "extractor",
            "chunk_index": idx, "content": content, "bbox": f.get("bbox"), "asset_id": f.get("asset_id"),
            "meta": {"figure_type": f.get("figure_type", "figure"), "caption": caption},
        })
        idx += 1

    # --- image chunks ---
    for im in images:
        caption = im.get("caption") or ""
        content = caption or f"[Image on page {im.get('page_number', 0)}]"
        out.append({
            "page_number": im.get("page_number", 0), "chunk_type": "image", "source": "extractor",
            "chunk_index": idx, "content": content, "bbox": im.get("bbox"), "asset_id": im.get("asset_id"),
            "meta": {"image_type": im.get("image_type", "raster"), "width": im.get("width", 0),
                     "height": im.get("height", 0), "caption": caption},
        })
        idx += 1

    return out
