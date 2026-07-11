"""Pure vision taxonomy + helpers (no I/O, no ORM)."""

from __future__ import annotations

# The image-classification taxonomy (Step 3). Grouped so analyzers know which structured extractor
# to run. Extend by adding a type here + a branch in the engine's structured analysis.
DIAGRAM_TYPES = ("architecture_diagram", "flowchart", "er_diagram", "uml", "network_diagram", "sequence_diagram")
CHART_TYPES = ("pie_chart", "bar_chart", "line_chart", "scatter_plot", "area_chart")
SCREENSHOT_TYPES = ("code_screenshot", "ui_screenshot")
OTHER_TYPES = ("table", "scientific_figure", "general_image")

IMAGE_TYPES = (*DIAGRAM_TYPES, *CHART_TYPES, *SCREENSHOT_TYPES, *OTHER_TYPES)

COMPLEXITY = ("low", "medium", "high")
MODEL_FAMILIES = ("clip", "siglip", "fake")

# The analysis "kind" each classification maps to → which structured extractor applies.
def analysis_kind(image_type: str) -> str:
    if image_type in DIAGRAM_TYPES:
        return "diagram"
    if image_type in CHART_TYPES:
        return "chart"
    if image_type in SCREENSHOT_TYPES:
        return "screenshot"
    if image_type == "table":
        return "table"
    return "figure"


def is_diagram(image_type: str) -> bool:
    return image_type in DIAGRAM_TYPES


def is_chart(image_type: str) -> bool:
    return image_type in CHART_TYPES


def normalize_image_type(raw: str | None) -> str:
    t = (raw or "general_image").strip().lower()
    return t if t in IMAGE_TYPES else "general_image"
