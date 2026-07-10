import subprocess
from typing import Any, Dict, Iterator, List, Optional

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


def complete(prompt: str) -> str:
    """Run the local LLM (Ollama) on a fully-assembled RAW prompt and return the text.

    Shared low-level completion used by the QA answer path and the summaries engine (which
    builds its own summarization prompt and must not be re-wrapped in the QA system prompt).
    """
    result = subprocess.run(
        ["ollama", "run", settings.llm_model],
        input=prompt.encode("utf-8"),  # force UTF-8 bytes (Ollama expects UTF-8)
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="ignore").strip()


def generate_answer(question: str, context: str) -> str:
    """Run the local LLM (Ollama) on the grounded QA prompt and return the answer text."""
    return complete(build_prompt(question, context))


# --- Module 4: chat prompt + streaming ---------------------------------------
CHAT_SYSTEM_PROMPT = """You are LexiMind, a precise research assistant.

Answer the user's latest message using ONLY the information in the provided context and the
conversation so far. If the context does not contain the answer, say you don't know based on the
provided documents. Be concise and cite naturally. Use Markdown for formatting when helpful."""


def build_chat_prompt(question: str, context: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
    """Assemble a chat prompt: system + recent conversation history + retrieved context + turn.

    `history` is a token-budgeted list of prior turns ({role, content}) chosen by
    `app.chat.memory` — the LLM gets continuity without exceeding the context window.
    """
    from app.chat.memory import render_history  # local import avoids a package cycle

    transcript = render_history(history or [])
    history_block = f"\nConversation so far:\n{transcript}\n" if transcript else ""
    return f"""{CHAT_SYSTEM_PROMPT}
{history_block}
Context:
{context}

User: {question}

Assistant:
"""


_SUMMARY_STYLE = {
    "quick": "Write ONE tight paragraph (an executive overview). No headings, no lists.",
    "standard": "Write 1–3 clear paragraphs suitable for study revision. Prose, not bullets.",
    "detailed": "Write a thorough, well-structured explanation (several paragraphs). Use Markdown sub-structure if helpful.",
    "bullet": "Write concise Markdown bullet points only (no paragraphs). One idea per bullet.",
    "chapterwise": "Summarize this section/chapter clearly in a few sentences of prose.",
}


def build_summary_prompt(summary_type: str, heading: str, context: str) -> str:
    """Assemble a grounded summarization prompt for one section.

    The context is the Phase-2 engineered context (deduped, ranked, budgeted, compressed) for this
    section — NOT the raw document. The LLM summarizes only what the context contains, so the
    output stays grounded and its citations map back to the retrieved evidence.
    """
    style = _SUMMARY_STYLE.get(summary_type, _SUMMARY_STYLE["standard"])
    return f"""You are LexiMind, a precise summarization assistant.

Summarize the section titled "{heading}" using ONLY the information in the context below.
Do not invent facts or add information not present in the context. If the context is thin, be
brief rather than speculative. {style}

Context:
{context}

Summary of "{heading}":
"""


def stream_answer(prompt: str) -> Iterator[str]:
    """Stream the local LLM (Ollama) token-by-token for the given fully-assembled prompt.

    Uses Popen so tokens surface progressively (the chat streaming endpoint forwards them over
    SSE). Falls back to a single yielded blob if streaming isn't available. Cancellation is
    handled by the caller closing the generator, which terminates the subprocess.
    """
    proc = subprocess.Popen(
        ["ollama", "run", settings.llm_model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()
        while True:
            chunk = proc.stdout.read(64)
            if not chunk:
                break
            yield chunk.decode("utf-8", errors="ignore")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # pragma: no cover
                proc.kill()


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
                    # Module 4: surface a confidence so chat citation cards can rank/shade.
                    "confidence": round(float(ev.evidence_score), 4),
                }
            )
    return out
