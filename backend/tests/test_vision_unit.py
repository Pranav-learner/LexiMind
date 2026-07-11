"""Unit tests for the Vision Intelligence analyzers + engine + embedder (pure, no CLIP/torch)."""

from __future__ import annotations

from app.vision import analyzers as A
from app.vision.engines import FakeVisionEmbedder, FakeVisionEngine


# ------------------------------------------------------------------ classification
def test_classify_maps_module1_hints():
    assert A.classify_asset({"asset_type": "table"})[0] == "table"
    assert A.classify_asset({"asset_type": "figure", "figure_type": "diagram"})[0] == "architecture_diagram"
    assert A.classify_asset({"asset_type": "figure", "figure_type": "flowchart"})[0] == "flowchart"
    assert A.classify_asset({"asset_type": "figure", "figure_type": "chart"})[0] == "bar_chart"
    assert A.classify_asset({"asset_type": "image", "image_type": "screenshot"})[0] == "ui_screenshot"
    assert A.classify_asset({"asset_type": "image", "image_type": "photo"})[0] == "general_image"


# ------------------------------------------------------------------ structured understanding
def test_table_understanding_infers_dtypes():
    s = A.build_structured({"asset_type": "table", "headers": ["Name", "Age", "Score"],
                            "cells": [["Alice", "30", "9.5"], ["Bob", "25", "8.0"]]}, "table")
    assert s["kind"] == "table" and s["n_rows"] == 2 and s["n_cols"] == 3
    dtypes = {c["name"]: c["dtype"] for c in s["columns"]}
    assert dtypes["Name"] == "text" and dtypes["Age"] == "number" and dtypes["Score"] == "number"


def test_diagram_understanding_parses_nodes_and_edges():
    s = A.build_structured({"asset_type": "figure", "figure_type": "diagram", "caption": "API → Auth → Retrieval → LLM"}, "architecture_diagram")
    assert s["kind"] == "diagram"
    assert s["nodes"] == ["API", "Auth", "Retrieval", "LLM"]
    assert s["edge_count"] == 3 and s["direction"] == "top-down"


def test_chart_and_screenshot_shapes():
    c = A.build_structured({"asset_type": "figure", "figure_type": "chart", "caption": "Sales by region"}, "bar_chart")
    assert c["kind"] == "chart" and "x_axis" in c and "y_axis" in c
    sc = A.build_structured({"asset_type": "image", "image_type": "screenshot"}, "ui_screenshot")
    assert sc["kind"] == "screenshot" and "components" in sc


def test_caption_is_meaningful():
    s = A.build_structured({"asset_type": "figure", "figure_type": "diagram", "caption": "A → B → C"}, "flowchart")
    cap = A.build_caption("flowchart", s, 3)
    assert "Flowchart" in cap and "A → B → C" in cap and "p.3" in cap


def test_keywords_topics_and_complexity():
    s = A.build_structured({"asset_type": "table", "headers": ["A", "B"], "cells": [["1", "2"]]}, "table")
    kw, topics = A.keywords_and_topics("table", s, "Table with columns A B")
    assert isinstance(kw, list) and "table" in topics
    assert A.complexity_of(s) == "low"
    big = A.build_structured({"asset_type": "table", "headers": [f"c{i}" for i in range(8)],
                              "cells": [[str(j) for j in range(8)] for _ in range(10)]}, "table")
    assert A.complexity_of(big) == "high"


# ------------------------------------------------------------------ embedder
def test_fake_embedder_is_deterministic():
    e = FakeVisionEmbedder()
    v1, model, family, dim = e.embed(b"", "same caption")
    v2, *_ = e.embed(b"", "same caption")
    v3, *_ = e.embed(b"", "different caption")
    assert v1 == v2 and v1 != v3
    assert dim == 16 and len(v1) == 16 and family == "fake"


# ------------------------------------------------------------------ fake engine contract
def test_fake_engine_emits_per_asset_analysis_and_embedding():
    assets = [{"asset_type": "table", "asset_id": "t1", "page_number": 1, "headers": ["A"], "cells": [["1"]]},
              {"asset_type": "figure", "asset_id": "f1", "page_number": 2, "figure_type": "diagram", "caption": "X → Y"}]
    events = list(FakeVisionEngine().process(None, assets, None))
    analyses = [e for e in events if e["type"] == "analysis"]
    embeds = [e for e in events if e["type"] == "embedding"]
    assert len(analyses) == 2 and len(embeds) == 2 and events[-1]["type"] == "final"
    assert analyses[0]["image_type"] == "table" and analyses[1]["image_type"] == "architecture_diagram"
