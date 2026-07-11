"""Query understanding — detect which modalities a query should search (Step 3).

Pure + dependency-light (its own tiny tokenizer, so it never pulls torch/rank_bm25). Extends the
Phase-1 query analysis concept to multiple modalities: a query may activate several retrievers at
once, and a modality named in the query is boosted in fusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set

_WORD = re.compile(r"[a-z0-9']+")

# Modality trigger vocabularies. A hit activates that retriever AND boosts its fusion weight.
_TRIGGERS: Dict[str, List[str]] = {
    "diagram": ["diagram", "architecture", "flowchart", "flow chart", "uml", "er diagram",
                "sequence diagram", "class diagram", "network diagram", "schema diagram"],
    "image": ["image", "picture", "figure", "screenshot", "photo", "visual", "chart", "graph",
              "plot", "pie chart", "bar chart", "line graph", "illustration", "logo", "icon"],
    "table": ["table", "column", "row", "cell", "spreadsheet", "values in", "tabular", "matrix"],
    "ocr": ["scanned", "ocr", "handwritten", "written in", "text in the image", "read the"],
    "metadata": ["title", "caption", "tag", "keyword", "named", "called", "labeled", "metadata"],
}

# Base fusion weights per modality (text is the backbone; metadata is a light signal).
BASE_WEIGHTS: Dict[str, float] = {
    "text": 1.0, "ocr": 0.8, "image": 0.7, "diagram": 0.75, "table": 0.75, "metadata": 0.5,
}
_INTENT_BOOST = 0.6  # added to a modality's weight when the query explicitly names it

# Text + metadata are always searched (the strongest general signals); the rest are conditional.
_ALWAYS = ("text", "metadata")


@dataclass
class IntentResult:
    query: str
    keywords: List[str]
    modalities: Set[str]
    weights: Dict[str, float]
    primary: str
    detected: List[str] = field(default_factory=list)  # explicitly-named modalities


def _tokens(text: str) -> List[str]:
    stop = {"the", "a", "an", "of", "in", "on", "is", "what", "how", "does", "do", "this",
            "that", "and", "or", "to", "for", "with", "explain", "show", "me", "find", "are"}
    return [w for w in _WORD.findall(text.lower()) if w not in stop and len(w) > 1]


def analyze_intent(query: str) -> IntentResult:
    q = (query or "").lower()
    detected: List[str] = []
    for modality, triggers in _TRIGGERS.items():
        if any(t in q for t in triggers):
            detected.append(modality)

    modalities: Set[str] = set(_ALWAYS) | set(detected)
    weights = {m: BASE_WEIGHTS.get(m, 0.5) for m in modalities}
    for m in detected:
        weights[m] = round(weights.get(m, 0.5) + _INTENT_BOOST, 3)

    # The primary modality is the strongest explicitly-named one, else text.
    primary = max(detected, key=lambda m: weights[m]) if detected else "text"
    return IntentResult(query=query, keywords=_tokens(query), modalities=modalities,
                        weights=weights, primary=primary, detected=detected)
