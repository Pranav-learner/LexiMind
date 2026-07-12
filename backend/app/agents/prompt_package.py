"""Prompt Package (Step 16) — the structured hand-off to the SINGLE answer pathway.

The runtime NEVER calls the LLM directly. It assembles a `PromptPackage` from the tool outputs
(evidence + citations) and the user request, `render()`s it to a raw prompt, and passes it to
`answer_service.complete()` — the one inference entry point for the whole system. Keeping this a
distinct, inspectable object (rather than an inline string) means the debug panel can preview exactly
what the model will see, and a future planner/agent can manipulate the package before inference.

The rendered prompt intentionally mirrors the existing answer-service prompt shape (system → context →
question) so agent answers are stylistically consistent with chat/QA answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

_SYSTEM = (
    "You are LexiMind's workspace agent. Answer the user's request using ONLY the tool evidence below. "
    "Cite claims with the bracketed [n] markers where present, and preserve timestamps/speakers when the "
    "evidence carries them. If the evidence does not contain the answer, say so plainly."
)


@dataclass
class PromptSection:
    title: str
    content: str


@dataclass
class PromptPackage:
    query: str
    system: str = _SYSTEM
    sections: List[PromptSection] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)

    def add_tool_evidence(self, tool: str, result) -> None:
        text = (result.context_text or "").strip()
        if text:
            self.sections.append(PromptSection(title=f"Evidence from {tool}", content=text))
        for c in (result.citations or []):
            self.citations.append(c)

    def render(self) -> str:
        if not self.sections:
            body = "(no tool evidence was gathered)"
        else:
            body = "\n\n".join(f"### {s.title}\n{s.content}" for s in self.sections)
        return f"{self.system}\n\nEvidence:\n{body}\n\nRequest: {self.query}\n\nAnswer:\n"

    def to_dict(self, *, preview: int = 4000) -> Dict[str, Any]:
        rendered = self.render()
        return {"system": self.system, "query": self.query,
                "sections": [{"title": s.title, "content": s.content[:1200]} for s in self.sections],
                "citation_count": len(self.citations), "rendered_preview": rendered[:preview],
                "char_length": len(rendered)}
