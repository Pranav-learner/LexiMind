"""Structured agent output (Step 9) — the citation-preserving deliverable every agent returns.

An agent's product is not a raw string: it's an ordered set of typed blocks (headings, prose,
tables, lists, code, citations, media/timeline references) that render deterministically to Markdown
today and to DOCX/PDF/slides in the future without re-running the agent. Every output carries its
source citations + references so the UI can jump-and-highlight and the export stays grounded.

`StructuredOutput` is intentionally a plain, serializable value object (no business logic) so it can
be persisted on the AgentTaskLog, previewed in the Agent Workspace, and exported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

BLOCK_TYPES = ("heading", "markdown", "list", "table", "code", "callout", "citations",
               "media_ref", "timeline_ref")


@dataclass
class OutputBlock:
    type: str                            # one of BLOCK_TYPES
    content: Any = None                  # str | list | dict depending on type
    level: int = 2                       # for headings
    label: str = ""                      # optional caption/label

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "content": self.content, "level": self.level, "label": self.label}

    # --- markdown rendering -------------------------------------------------
    def to_markdown(self) -> str:
        t = self.type
        if t == "heading":
            return f"{'#' * max(1, min(6, self.level))} {self.content}"
        if t == "markdown":
            return str(self.content or "")
        if t == "code":
            lang = self.label or ""
            return f"```{lang}\n{self.content}\n```"
        if t == "callout":
            body = str(self.content or "")
            return "\n".join(f"> {line}" for line in body.splitlines()) or "> "
        if t == "list":
            items = self.content or []
            return "\n".join(f"- {i}" for i in items)
        if t == "table":
            return _render_table(self.content or {})
        if t == "citations":
            return _render_citations(self.content or [])
        if t in ("media_ref", "timeline_ref"):
            return _render_refs(self.label or "References", self.content or [])
        return str(self.content or "")


@dataclass
class StructuredOutput:
    title: str
    format: str = "markdown"             # markdown (docx/pdf/pptx are future renderers)
    summary: str = ""                    # one-line abstract for history/preview cards
    blocks: List[OutputBlock] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    references: List[Dict[str, Any]] = field(default_factory=list)   # {kind, document_id, title, …}

    # --- builders (fluent, so agents read top-to-bottom) --------------------
    def heading(self, text: str, level: int = 2) -> "StructuredOutput":
        self.blocks.append(OutputBlock("heading", text, level=level)); return self

    def markdown(self, text: str) -> "StructuredOutput":
        if (text or "").strip():
            self.blocks.append(OutputBlock("markdown", text.strip()))
        return self

    def bullet_list(self, items: List[str], label: str = "") -> "StructuredOutput":
        items = [i for i in (items or []) if str(i).strip()]
        if items:
            self.blocks.append(OutputBlock("list", items, label=label))
        return self

    def table(self, headers: List[str], rows: List[List[Any]], label: str = "") -> "StructuredOutput":
        self.blocks.append(OutputBlock("table", {"headers": headers, "rows": rows}, label=label))
        return self

    def code(self, text: str, lang: str = "") -> "StructuredOutput":
        self.blocks.append(OutputBlock("code", text, label=lang)); return self

    def callout(self, text: str) -> "StructuredOutput":
        if (text or "").strip():
            self.blocks.append(OutputBlock("callout", text.strip()))
        return self

    def add_citations(self, citations: List[Dict[str, Any]]) -> "StructuredOutput":
        for c in (citations or []):
            self.citations.append(c)
        return self

    def add_reference(self, kind: str, *, document_id: Optional[str] = None, title: Optional[str] = None,
                      route: Optional[str] = None, timespan: Optional[str] = None) -> "StructuredOutput":
        ref = {"kind": kind, "document_id": document_id, "title": title, "route": route,
               "timespan": timespan}
        if ref not in self.references:
            self.references.append(ref)
        return self

    def citations_section(self, heading: str = "Citations") -> "StructuredOutput":
        if self.citations:
            self.heading(heading, level=2)
            self.blocks.append(OutputBlock("citations", self.citations))
        return self

    # --- serialization / rendering -----------------------------------------
    def to_markdown(self) -> str:
        parts = [f"# {self.title}"] if self.title else []
        parts += [b.to_markdown() for b in self.blocks]
        return "\n\n".join(p for p in parts if p is not None)

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "format": self.format, "summary": self.summary,
                "blocks": [b.to_dict() for b in self.blocks], "markdown": self.to_markdown(),
                "citations": self.citations, "references": self.references}


# --------------------------------------------------------------------- markdown helpers
def _render_table(spec: Dict[str, Any]) -> str:
    headers = spec.get("headers") or []
    rows = spec.get("rows") or []
    if not headers:
        return ""
    def esc(v: Any) -> str:
        return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")
    head = "| " + " | ".join(esc(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(esc(c) for c in row) + " |" for row in rows)
    return "\n".join([head, sep, body]) if body else "\n".join([head, sep])


def _render_citations(citations: List[Dict[str, Any]]) -> str:
    lines = []
    for i, c in enumerate(citations, start=1):
        idx = c.get("index", i)
        bits = []
        if c.get("title"):
            bits.append(str(c["title"]))
        if c.get("source"):
            bits.append(str(c["source"]))
        if c.get("page_number") is not None:
            bits.append(f"p{c['page_number']}")
        if c.get("timespan"):
            bits.append(str(c["timespan"]))
        if c.get("speaker_label"):
            bits.append(str(c["speaker_label"]))
        text = (c.get("text") or "").strip().replace("\n", " ")
        label = " · ".join(bits) if bits else (c.get("document_id") or "source")
        lines.append(f"- **[{idx}]** {label}" + (f" — {text[:160]}" if text else ""))
    return "\n".join(lines)


def _render_refs(label: str, refs: List[Dict[str, Any]]) -> str:
    lines = [f"**{label}:**"]
    for r in refs:
        name = r.get("title") or r.get("document_id") or "reference"
        ts = f" @ {r['timespan']}" if r.get("timespan") else ""
        lines.append(f"- {name}{ts}")
    return "\n".join(lines)
