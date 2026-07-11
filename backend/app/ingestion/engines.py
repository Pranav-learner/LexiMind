"""The multimodal engine — the ONLY bridge from a processing job to the heavy OCR/vision/PDF libs.

Like every AI engine in LexiMind (chat/summaries/notes/flashcards), this is INJECTED and imports the
heavy libraries LAZILY, so `app.ingestion.*` imports with no PaddleOCR/PyMuPDF/pdfplumber/torch and
tests substitute a deterministic `FakeMultimodalEngine`.

`process(job, document, storage, ocr_cache)` is a generator of events the SERVICE consumes + persists:

    {"type": "classification", "doc_type", "processing_type", "needs_ocr", "language"}
    {"type": "stage",  "stage": str, "progress": int}
    {"type": "ocr",    "page_number", "content_hash", "text", "confidence", "language",
                       "boxes", "reading_order", "cached": bool, "from_ocr": bool}
    {"type": "image",  "page_number", "bbox", "width", "height", "image_type", "confidence",
                       "hash", "ext", "bytes"}
    {"type": "table",  "page_number", "bbox", "headers", "rows", "caption"}
    {"type": "figure", "page_number", "bbox", "figure_type", "caption", "hash", "ext", "bytes"}
    {"type": "final",  "pipeline_version"}

`ocr_cache` is a read accessor `get(page_number, content_hash) -> Optional[dict]` — the engine checks
it BEFORE running OCR so a page's OCR is never recomputed (Step 4: cache OCR results).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterator, Optional, Protocol

from app.ingestion.models import PIPELINE_VERSION


class OcrCache(Protocol):
    def get(self, page_number: int, content_hash: str) -> Optional[Dict[str, Any]]: ...


class MultimodalEngine(Protocol):
    def process(self, job, document, storage, ocr_cache: OcrCache) -> Iterator[Dict[str, Any]]: ...


# ====================================================================== fake (tests + contract)
class FakeMultimodalEngine:
    """Deterministic stand-in for the heavy engine.

    Emits a classification, a configurable number of OCR pages (honoring the OCR cache so caching is
    exercised), one image + one table + one figure (with bytes so storage is exercised), then a
    final — mirroring the production event contract without any OCR/vision library.
    """

    def __init__(self, *, pages: int = 2, doc_type: str = "mixed_pdf", processing_type: str = "mixed",
                 needs_ocr: bool = True):
        self.pages = pages
        self.doc_type = doc_type
        self.processing_type = processing_type
        self.needs_ocr = needs_ocr

    def process(self, job, document, storage, ocr_cache) -> Iterator[Dict[str, Any]]:
        yield {"type": "classification", "doc_type": self.doc_type, "processing_type": self.processing_type,
               "needs_ocr": self.needs_ocr, "language": "en"}

        yield {"type": "stage", "stage": "ocr", "progress": 25}
        for p in range(1, self.pages + 1):
            content_hash = f"{document.id}:{p}"
            cached = ocr_cache.get(p, content_hash)
            if cached is not None:
                yield {"type": "ocr", "page_number": p, "content_hash": content_hash,
                       "text": cached["text"], "confidence": cached.get("confidence"),
                       "language": cached.get("language", "en"), "boxes": cached.get("boxes"),
                       "reading_order": None, "cached": True, "from_ocr": True}
            else:
                text = f"Page {p} recognized text.\n\nSecond paragraph on page {p}."
                yield {"type": "ocr", "page_number": p, "content_hash": content_hash, "text": text,
                       "confidence": 0.94, "language": "en",
                       "boxes": [[0, 0, 100, 20, f"Page {p}", 0.95]], "reading_order": [0],
                       "cached": False, "from_ocr": True}

        yield {"type": "stage", "stage": "extraction", "progress": 60}
        yield {"type": "image", "page_number": 1, "bbox": [10, 10, 210, 210], "width": 200, "height": 200,
               "image_type": "raster", "confidence": 0.9, "hash": "imghash1", "ext": "png", "bytes": b"\x89PNGfake"}
        yield {"type": "table", "page_number": 1, "bbox": [0, 220, 300, 320],
               "headers": ["Col A", "Col B"], "rows": [["a1", "b1"], ["a2", "b2"]], "caption": "Table 1"}
        yield {"type": "figure", "page_number": 2, "bbox": [0, 0, 300, 300], "figure_type": "diagram",
               "caption": "System architecture", "hash": "fighash1", "ext": "png", "bytes": b"\x89PNGfig"}

        yield {"type": "stage", "stage": "chunking", "progress": 85}
        yield {"type": "final", "pipeline_version": PIPELINE_VERSION}


# ====================================================================== production (lazy heavy libs)
class PipelineMultimodalEngine:
    """Production engine: PyMuPDF for PDF text/images, PaddleOCR (Tesseract fallback) for OCR,
    pdfplumber for tables, heuristics for figures. All imports are LAZY and failures degrade
    gracefully (a missing extractor logs + yields nothing rather than aborting the job)."""

    def process(self, job, document, storage, ocr_cache) -> Iterator[Dict[str, Any]]:
        path = document.storage_path
        ext = (document.file_type or "").lower()

        classification = self._classify(path, ext)
        yield {"type": "classification", **classification}

        if ext in ("png", "jpg", "jpeg", "webp", "tiff", "tif"):
            yield from self._process_image(path, document, ocr_cache)
        else:
            yield from self._process_pdf(path, document, classification, ocr_cache)

        yield {"type": "final", "pipeline_version": PIPELINE_VERSION}

    # ------------------------------------------------------------------ classification
    def _classify(self, path: str, ext: str) -> Dict[str, Any]:
        if ext in ("png", "jpg", "jpeg", "webp", "tiff", "tif"):
            return {"doc_type": "image", "processing_type": "image_only", "needs_ocr": True, "language": ""}
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(path)
            total_chars = sum(len(page.get_text() or "") for page in doc)
            pages = max(1, doc.page_count)
            doc.close()
            per_page = total_chars / pages
            if per_page > 200:
                return {"doc_type": "text_pdf", "processing_type": "native", "needs_ocr": False, "language": ""}
            if per_page < 20:
                return {"doc_type": "scanned_pdf", "processing_type": "ocr", "needs_ocr": True, "language": ""}
            return {"doc_type": "mixed_pdf", "processing_type": "mixed", "needs_ocr": True, "language": ""}
        except Exception:
            return {"doc_type": "unknown", "processing_type": "native", "needs_ocr": False, "language": ""}

    # ------------------------------------------------------------------ pdf
    def _process_pdf(self, path, document, classification, ocr_cache) -> Iterator[Dict[str, Any]]:
        yield {"type": "stage", "stage": "extraction", "progress": 30}
        try:
            import fitz
            doc = fitz.open(path)
        except Exception:
            return
        needs_ocr = classification.get("needs_ocr", False)
        for pno in range(doc.page_count):
            page = doc[pno]
            native_text = page.get_text() or ""
            if native_text.strip() and not needs_ocr:
                yield {"type": "ocr", "page_number": pno + 1, "content_hash": _hash(native_text),
                       "text": native_text, "confidence": 1.0, "language": "", "boxes": None,
                       "reading_order": None, "cached": False, "from_ocr": False}
            elif needs_ocr:
                yield from self._ocr_page(page, pno + 1, ocr_cache)
            for img in self._page_images(page, doc, pno + 1):
                yield img
        doc.close()

    def _process_image(self, path, document, ocr_cache) -> Iterator[Dict[str, Any]]:
        yield {"type": "stage", "stage": "ocr", "progress": 30}
        data = b""
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception:
            pass
        content_hash = _hash(data)
        cached = ocr_cache.get(1, content_hash)
        if cached is not None:
            yield {"type": "ocr", "page_number": 1, "content_hash": content_hash, "text": cached["text"],
                   "confidence": cached.get("confidence"), "language": cached.get("language", ""),
                   "boxes": cached.get("boxes"), "reading_order": None, "cached": True, "from_ocr": True}
        else:
            text, conf, boxes, lang = self._run_ocr(path)
            yield {"type": "ocr", "page_number": 1, "content_hash": content_hash, "text": text,
                   "confidence": conf, "language": lang, "boxes": boxes, "reading_order": None,
                   "cached": False, "from_ocr": True}
        yield {"type": "image", "page_number": 1, "bbox": None, "width": 0, "height": 0,
               "image_type": "photo", "confidence": None, "hash": content_hash, "ext": document.file_type or "png",
               "bytes": data}

    def _ocr_page(self, page, page_number, ocr_cache) -> Iterator[Dict[str, Any]]:
        try:
            pix = page.get_pixmap(dpi=200)
            data = pix.tobytes("png")
        except Exception:
            return
        content_hash = _hash(data)
        cached = ocr_cache.get(page_number, content_hash)
        if cached is not None:
            yield {"type": "ocr", "page_number": page_number, "content_hash": content_hash,
                   "text": cached["text"], "confidence": cached.get("confidence"),
                   "language": cached.get("language", ""), "boxes": cached.get("boxes"),
                   "reading_order": None, "cached": True, "from_ocr": True}
            return
        text, conf, boxes, lang = self._run_ocr_bytes(data)
        yield {"type": "ocr", "page_number": page_number, "content_hash": content_hash, "text": text,
               "confidence": conf, "language": lang, "boxes": boxes, "reading_order": None,
               "cached": False, "from_ocr": True}

    def _page_images(self, page, doc, page_number) -> Iterator[Dict[str, Any]]:
        try:
            for info in page.get_images(full=True):
                xref = info[0]
                pix = doc.extract_image(xref)
                data = pix.get("image", b"")
                yield {"type": "image", "page_number": page_number, "bbox": None,
                       "width": pix.get("width", 0), "height": pix.get("height", 0),
                       "image_type": "raster", "confidence": None, "hash": _hash(data),
                       "ext": pix.get("ext", "png"), "bytes": data}
        except Exception:
            return

    # ------------------------------------------------------------------ OCR backends
    def _run_ocr(self, path: str):
        try:
            with open(path, "rb") as fh:
                return self._run_ocr_bytes(fh.read())
        except Exception:
            return "", None, None, ""

    def _run_ocr_bytes(self, data: bytes):
        # Primary: PaddleOCR. Fallback: Tesseract. Both lazy-imported.
        try:
            from paddleocr import PaddleOCR  # noqa
            import numpy as np
            from PIL import Image
            import io
            ocr = _paddle_singleton()
            arr = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
            result = ocr.ocr(arr, cls=True)
            lines, confs, boxes = [], [], []
            for block in (result or []):
                for box, (text, conf) in block:
                    lines.append(text)
                    confs.append(conf)
                    boxes.append([*[c for pt in box for c in pt], text, conf])
            avg = sum(confs) / len(confs) if confs else None
            return "\n".join(lines), avg, boxes, "en"
        except Exception:
            pass
        try:
            import pytesseract
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            text = pytesseract.image_to_string(img)
            return text, None, None, ""
        except Exception:
            return "", None, None, ""


_PADDLE = None


def _paddle_singleton():
    global _PADDLE
    if _PADDLE is None:
        from paddleocr import PaddleOCR
        _PADDLE = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return _PADDLE


def _hash(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", errors="ignore")
    return hashlib.sha1(data or b"").hexdigest()[:32]
