"""Metadata filtering helpers.

The filter data structure itself (`RetrievalFilter`) lives in schemas.py because both
the retrievers and the pipeline depend on it. This module is the public, API-facing
entry point: it turns a loose request dict (from the /query endpoint or a future agent)
into a validated RetrievalFilter, and is the place to grow validation/normalization as
filterable facets expand (modality, date ranges, tags).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.retrieval.schemas import RetrievalFilter

_ALLOWED_FIELDS = {"document_id", "workspace", "source", "topic"}


def build_filter(raw: Optional[Dict[str, Any]]) -> Optional[RetrievalFilter]:
    """Build a RetrievalFilter from a request dict, or None if there's nothing to filter.

    Unknown keys are ignored (forward-compatible: an older backend won't 500 on a
    filter facet it doesn't understand yet). Empty/whitespace values are dropped.
    """
    if not raw:
        return None

    cleaned: Dict[str, Any] = {}
    for key in _ALLOWED_FIELDS:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if isinstance(value, list):
            value = [v.strip() if isinstance(v, str) else v for v in value if str(v).strip()]
            if not value:
                continue
        cleaned[key] = value

    if not cleaned:
        return None

    f = RetrievalFilter(**cleaned)
    return None if f.is_empty() else f
