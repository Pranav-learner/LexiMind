"""Vision analyzers — pure structured-understanding builders (no I/O, no ORM, no torch).

One builder per visual kind (diagram / chart / table / screenshot / figure), plus classification,
captioning, and keyword/complexity helpers. These are:
- the REAL implementation for tables (structure is derived directly from the extracted headers/cells);
- deterministic, model-free scaffolding for diagrams/charts/screenshots (the production engine swaps
  in vision-language models but reuses this same OUTPUT SHAPE, so downstream consumers never change).

Being pure makes every analyzer independently unit-testable without CLIP/BLIP installed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.vision.validation import analysis_kind, normalize_image_type

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{2,}")


# ------------------------------------------------------------------ classification
def classify_asset(asset: Dict[str, Any]) -> Tuple[str, float]:
    """Map a Module-1 extracted asset to a fine-grained image type + confidence.

    Uses the coarse hints Module 1 already stored (figure_type, image_type, table-ness) — a real
    vision classifier refines this, but the taxonomy + contract are identical.
    """
    atype = asset.get("asset_type")
    if atype == "table":
        return "table", 0.98
    if atype == "figure":
        ftype = (asset.get("figure_type") or "figure").lower()
        mapping = {
            "diagram": "architecture_diagram", "flowchart": "flowchart", "chart": "bar_chart",
            "equation": "scientific_figure", "figure": "scientific_figure",
        }
        return mapping.get(ftype, "scientific_figure"), 0.8
    # image asset
    itype = (asset.get("image_type") or "raster").lower()
    if itype == "screenshot":
        return "ui_screenshot", 0.75
    if itype == "photo":
        return "general_image", 0.7
    return "general_image", 0.6


# ------------------------------------------------------------------ structured analysis
def analyze_diagram(asset: Dict[str, Any], image_type: str) -> Dict[str, Any]:
    """Diagram understanding: nodes, connections, direction, hierarchy (Step 5).

    Model-free scaffold (a real diagram parser fills nodes/edges from detected shapes+arrows). Uses
    the caption/label hints available so the shape is populated deterministically.
    """
    label = (asset.get("caption") or "").strip()
    nodes = _labels_from(label) or ["Component A", "Component B", "Component C"]
    edges = [{"from": nodes[i], "to": nodes[i + 1], "kind": "flow"} for i in range(len(nodes) - 1)]
    return {
        "kind": "diagram", "diagram_type": image_type,
        "nodes": nodes, "edges": edges,
        "direction": "top-down" if image_type in ("flowchart", "architecture_diagram") else "undirected",
        "hierarchy_depth": len(nodes), "node_count": len(nodes), "edge_count": len(edges),
    }


def analyze_chart(asset: Dict[str, Any], image_type: str) -> Dict[str, Any]:
    """Chart understanding: title, axes, legend, series, trend (Step 7). Model-free scaffold."""
    title = (asset.get("caption") or "Chart").strip()
    return {
        "kind": "chart", "chart_type": image_type, "title": title,
        "x_axis": {"label": "category", "type": "categorical"},
        "y_axis": {"label": "value", "type": "numeric"},
        "legend": [], "series": [], "values_extracted": False,
        "trend": "unknown",
    }


def analyze_table(asset: Dict[str, Any]) -> Dict[str, Any]:
    """Table understanding — REAL: derives schema + inferred column data-types from the extracted
    headers/cells (Step 6), going beyond OCR."""
    headers = asset.get("headers") or []
    cells = asset.get("cells") or []
    n_rows = len(cells)
    n_cols = len(headers) or (len(cells[0]) if cells else 0)
    columns = []
    for c in range(n_cols):
        name = str(headers[c]) if c < len(headers) else f"col_{c + 1}"
        sample = [row[c] for row in cells if c < len(row)]
        columns.append({"name": name, "dtype": _infer_dtype(sample)})
    return {
        "kind": "table", "headers": [str(h) for h in headers], "n_rows": n_rows, "n_cols": n_cols,
        "columns": columns, "has_merged_cells": False,
        "relationships": [{"type": "column", "name": col["name"]} for col in columns],
    }


def analyze_screenshot(asset: Dict[str, Any], image_type: str) -> Dict[str, Any]:
    """Screenshot understanding: components, layout, visible text (Step 8). Model-free scaffold."""
    kind = "code" if image_type == "code_screenshot" else "ui"
    return {
        "kind": "screenshot", "screenshot_type": image_type, "surface": kind,
        "components": ["header", "content", "actions"] if kind == "ui" else ["editor"],
        "layout": "single-column", "menus": [], "buttons": [], "forms": [],
        "visible_text": (asset.get("caption") or "")[:500],
    }


def analyze_figure(asset: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": "figure", "description": (asset.get("caption") or "").strip()}


def build_structured(asset: Dict[str, Any], image_type: str) -> Dict[str, Any]:
    kind = analysis_kind(image_type)
    if kind == "diagram":
        return analyze_diagram(asset, image_type)
    if kind == "chart":
        return analyze_chart(asset, image_type)
    if kind == "table":
        return analyze_table(asset)
    if kind == "screenshot":
        return analyze_screenshot(asset, image_type)
    return analyze_figure(asset)


# ------------------------------------------------------------------ captions + metadata
def build_caption(image_type: str, structured: Dict[str, Any], page_number: int) -> str:
    """Compose a semantic, retrieval-worthy caption from the structured understanding (Step 4)."""
    it = image_type.replace("_", " ")
    if structured.get("kind") == "diagram":
        nodes = structured.get("nodes", [])
        flow = " → ".join(nodes[:6]) if nodes else "components"
        return f"{it.title()} (p.{page_number}) showing: {flow}."
    if structured.get("kind") == "chart":
        return f"{it.title()} (p.{page_number}) titled “{structured.get('title', 'Chart')}” with a {structured.get('x_axis', {}).get('label', 'category')} axis and a {structured.get('y_axis', {}).get('label', 'value')} axis."
    if structured.get("kind") == "table":
        cols = ", ".join(c["name"] for c in structured.get("columns", [])[:6])
        return f"Table (p.{page_number}) with {structured.get('n_rows', 0)} rows and columns: {cols}."
    if structured.get("kind") == "screenshot":
        return f"{it.title()} (p.{page_number}) of a {structured.get('surface', 'UI')} showing {', '.join(structured.get('components', []))}."
    return f"{it.title()} on page {page_number}."


def keywords_and_topics(image_type: str, structured: Dict[str, Any], caption: str) -> Tuple[List[str], List[str]]:
    text = f"{image_type} {caption} " + " ".join(str(v) for v in _flatten(structured))
    words = [w.lower() for w in _WORD.findall(text)]
    stop = {"the", "and", "with", "showing", "page", "axis", "value", "category", "component"}
    freq: Dict[str, int] = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    keywords = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:10]]
    topics = list(dict.fromkeys([image_type.split("_")[0], structured.get("kind", "figure")]))
    return keywords, topics


def complexity_of(structured: Dict[str, Any]) -> str:
    kind = structured.get("kind")
    if kind == "diagram":
        n = structured.get("node_count", 0)
        return "high" if n >= 8 else "medium" if n >= 4 else "low"
    if kind == "table":
        cells = structured.get("n_rows", 0) * structured.get("n_cols", 0)
        return "high" if cells >= 50 else "medium" if cells >= 12 else "low"
    if kind in ("chart", "screenshot"):
        return "medium"
    return "low"


# ------------------------------------------------------------------ helpers
def _labels_from(text: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[\n,→>/;|]+", text) if p.strip()]
    return [p[:60] for p in parts][:12]


def _infer_dtype(sample: List[Any]) -> str:
    vals = [str(s).strip() for s in sample if str(s).strip()]
    if not vals:
        return "unknown"
    def is_num(x):
        try:
            float(x.replace(",", ""))
            return True
        except ValueError:
            return False
    if all(is_num(v) for v in vals):
        return "number"
    return "text"


def _flatten(obj) -> List[Any]:
    out: List[Any] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flatten(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_flatten(v))
    else:
        out.append(obj)
    return out


__all__ = [
    "classify_asset", "build_structured", "build_caption", "keywords_and_topics", "complexity_of",
    "analyze_diagram", "analyze_chart", "analyze_table", "analyze_screenshot", "normalize_image_type",
]
