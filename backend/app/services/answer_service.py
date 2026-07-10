import subprocess
from typing import Any, Dict, List

from app.core.config import settings
from app.context.schemas import Citation, Evidence

# Static, grounded system instructions. Kept small (within the system-prompt token reserve).
SYSTEM_PROMPT = """You are a precise question-answering assistant.

TASK:
Answer ONLY the question below.
Use ONLY the information present in the context.
DO NOT add extra explanations.
DO NOT include future topics or applications.
DO NOT infer beyond the context.

If the context does not explicitly contain the answer, say:
"I don't know based on the provided document."

FORMAT RULES:
- Answer in bullet points
- Maximum 5 bullet points
- One line per bullet"""


def build_prompt(question: str, context: str) -> str:
    """Assemble the final LLM prompt from the system prompt, context, and question.

    The context is produced by the Phase-2 ContextBuilderService (deduped, ranked,
    budgeted, compressed, assembled with [n] citation markers) — this function no longer
    builds context itself, removing the pre-Phase-2 duplicate context builder.
    """
    return f"""{SYSTEM_PROMPT}

Context:
{context}

Question:
{question}

Answer:
"""


def generate_answer(question: str, context: str) -> str:
    """Run the local LLM (Ollama) on the grounded prompt and return the answer text."""
    prompt = build_prompt(question, context)

    result = subprocess.run(
        ["ollama", "run", settings.llm_model],
        input=prompt.encode("utf-8"),  # force UTF-8 bytes (Ollama expects UTF-8)
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="ignore").strip()


def format_citations(citations: List[Citation]) -> str:
    """Render Phase-2 Citation objects as deduplicated source lines for the API/UI."""
    lines = []
    seen = set()
    for i, c in enumerate(citations, start=1):
        key = (c.source, c.page_number, c.section, c.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        parts = [f"[{i}]", c.source or "unknown"]
        if c.page_number is not None:
            parts.append(f"Page {c.page_number}")
        if c.section:
            parts.append(f"Section: {c.section}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def structured_citations(evidence: List[Evidence]) -> List[Dict[str, Any]]:
    """Machine-readable citations for the PDF Viewer (Module 3).

    Unlike `format_citations` (a display string), this returns one object per source chunk with
    the fields the viewer needs to jump-and-highlight: the vector `document_id` (resolvable to a
    Document row), `source` filename, `page_number`, `section`, and a short `text` snippet to
    highlight in the page's text layer. Deduplicated by chunk_id, order preserved.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for ev in evidence:
        for c in ev.citations:
            if c.chunk_id in seen:
                continue
            seen.add(c.chunk_id)
            out.append(
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "source": c.source,
                    "page_number": c.page_number,
                    "section": c.section,
                    "text": (ev.text or "")[:400],
                }
            )
    return out
