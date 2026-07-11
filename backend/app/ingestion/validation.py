"""Pure validation + format registry for multimodal ingestion (no I/O, no ORM)."""

from __future__ import annotations

from app.ingestion.errors import UnsupportedMedia

# Supported now. Designed for easy extension — add an entry + a branch in classification/engine.
PDF_TYPES = {"pdf": "application/pdf"}
IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
}
# Future-ready (declared but NOT processed yet). Kept here so the registry is the single source of
# truth and adding support later is a one-line change.
FUTURE_TYPES = {"docx", "pptx", "epub", "html", "htm"}

SUPPORTED_TYPES = {**PDF_TYPES, **IMAGE_TYPES}

DOC_TYPES = ("text_pdf", "scanned_pdf", "mixed_pdf", "image", "screenshot", "photo", "unknown")
PROCESSING_TYPES = ("native", "ocr", "mixed", "image_only")
CHUNK_TYPES = ("text", "ocr", "image", "table", "figure")


def normalize_ext(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").strip().lower()


def is_image(ext: str) -> bool:
    return ext in IMAGE_TYPES


def is_pdf(ext: str) -> bool:
    return ext in PDF_TYPES


def validate_supported(ext: str) -> str:
    """Ensure a file type can be multimodally processed (415 otherwise)."""
    e = ext.strip().lower()
    if e in FUTURE_TYPES:
        raise UnsupportedMedia(f"{e} (planned, not yet supported)")
    if e not in SUPPORTED_TYPES:
        raise UnsupportedMedia(e or "unknown")
    return e


def mime_for(ext: str) -> str:
    return SUPPORTED_TYPES.get(ext.strip().lower(), "application/octet-stream")
