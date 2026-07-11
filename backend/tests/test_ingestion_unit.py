"""Unit tests for multimodal ingestion: chunking, validation, storage, fake engine + OCR cache."""

from __future__ import annotations

import pytest

from app.ingestion import validation as v
from app.ingestion.chunking import build_multimodal_chunks
from app.ingestion.engines import FakeMultimodalEngine
from app.ingestion.errors import UnsupportedMedia
from app.ingestion.storage import AssetStorage


# ------------------------------------------------------------------ validation
def test_supported_and_future_types():
    assert v.validate_supported("PNG") == "png"
    assert v.validate_supported("pdf") == "pdf"
    with pytest.raises(UnsupportedMedia):
        v.validate_supported("docx")   # future, not yet supported
    with pytest.raises(UnsupportedMedia):
        v.validate_supported("mp3")
    assert v.is_image("jpeg") and v.is_pdf("pdf") and not v.is_image("pdf")


# ------------------------------------------------------------------ chunking
def test_multimodal_chunking_covers_all_types():
    chunks = build_multimodal_chunks(
        ocr_pages=[{"page_number": 1, "text": "A para.\n\nB para.", "confidence": 0.9, "from_ocr": True}],
        images=[{"page_number": 1, "asset_id": "img1", "image_type": "photo"}],
        tables=[{"page_number": 1, "asset_id": "tbl1", "headers": ["H"], "cells": [["x"]]}],
        figures=[{"page_number": 2, "asset_id": "fig1", "figure_type": "chart", "caption": "Growth"}],
    )
    kinds = {c["chunk_type"] for c in chunks}
    assert kinds == {"ocr", "image", "table", "figure"}
    # Chunk indices are a contiguous running order.
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    # Table chunk carries a searchable serialization; figure uses its caption.
    tbl = next(c for c in chunks if c["chunk_type"] == "table")
    assert "H" in tbl["content"]
    fig = next(c for c in chunks if c["chunk_type"] == "figure")
    assert fig["content"] == "Growth"


def test_native_pages_produce_text_chunks():
    chunks = build_multimodal_chunks(
        ocr_pages=[{"page_number": 1, "text": "Native text.", "from_ocr": False}],
        images=[], tables=[], figures=[])
    assert chunks and chunks[0]["chunk_type"] == "text" and chunks[0]["source"] == "native"


def test_word_window_splits_long_text():
    long_text = "\n\n".join(f"word " * 60 for _ in range(6))  # ~360 words → multiple windows
    chunks = build_multimodal_chunks(
        ocr_pages=[{"page_number": 1, "text": long_text, "from_ocr": True}], images=[], tables=[], figures=[])
    assert len(chunks) >= 2  # split into >1 window at the 250-word budget


# ------------------------------------------------------------------ storage
def test_asset_storage_writes_files(tmp_path):
    s = AssetStorage(root=str(tmp_path))
    path = s.write_asset("w1", "d1", "images", "img1", b"\x89PNG", "png")
    assert s.exists(path)
    assert path.endswith("img1.png")


# ------------------------------------------------------------------ fake engine honours the OCR cache
def test_fake_engine_uses_ocr_cache():
    class Doc:  # minimal stand-in
        id = "d1"
        storage_path = ""
        file_type = "pdf"

    class Cache:
        def __init__(self, hit): self.hit = hit
        def get(self, page, content_hash):
            return {"text": "cached", "confidence": 0.5, "language": "en", "boxes": None} if self.hit else None

    # Cache miss → engine produces fresh OCR text (cached=False).
    events = list(FakeMultimodalEngine(pages=1).process(None, Doc(), None, Cache(False)))
    ocr = next(e for e in events if e["type"] == "ocr")
    assert ocr["cached"] is False and "recognized" in ocr["text"]

    # Cache hit → engine reuses cached text (cached=True), no re-OCR.
    events = list(FakeMultimodalEngine(pages=1).process(None, Doc(), None, Cache(True)))
    ocr = next(e for e in events if e["type"] == "ocr")
    assert ocr["cached"] is True and ocr["text"] == "cached"


def test_fake_engine_emits_full_contract():
    class Doc: id = "d1"; storage_path = ""; file_type = "pdf"
    types = [e["type"] for e in FakeMultimodalEngine(pages=2).process(None, Doc(), None, type("C", (), {"get": lambda *_: None})())]
    assert "classification" in types and types[-1] == "final"
    assert types.count("ocr") == 2 and "image" in types and "table" in types and "figure" in types
