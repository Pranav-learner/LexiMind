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


# --- Module 6: Smart Notes prompts -------------------------------------------
# Note generation is deliberately STRUCTURED (headings, bullets, key concepts, examples) — never
# plain prose — so the output drops straight into the Markdown editor as usable study material.
_NOTE_STYLE = {
    "quick": "Write terse, scannable bullet points capturing only the essential facts. No filler.",
    "study": (
        "Produce study notes: a short intro sentence, then **Key points** as bullets, a "
        "**Key concepts** mini-glossary (term — definition), and an **Example** if the context "
        "supports one. Use Markdown bullets and bold labels."
    ),
    "detailed": (
        "Produce thorough notes: explanatory bullets grouped under bold sub-labels, definitions of "
        "any jargon, and worked examples where the context allows. Be comprehensive but grounded."
    ),
    "chapterwise": "Summarize this section as structured notes: 3–6 bullets plus any key terms.",
    "concept": (
        "Explain the core concept(s) as notes: **Definition**, **Why it matters**, **How it works** "
        "(bullets), and a concrete **Example**. Ground every claim in the context."
    ),
    "revision": (
        "Write revision notes: crisp recall bullets and a short **Remember** list of the most "
        "test-worthy facts. Optimize for last-minute review."
    ),
}


def build_notes_prompt(note_type: str, heading: str, context: str) -> str:
    """Assemble a grounded, STRUCTURED note-generation prompt for one section.

    Like the summary prompt, `context` is the Phase-2 engineered context (deduped, ranked,
    budgeted, compressed) for this section — NOT the raw document — so the notes stay grounded and
    their citations map back to retrieved evidence. The style rules force headings/bullets/examples
    rather than a paragraph blob.
    """
    style = _NOTE_STYLE.get(note_type, _NOTE_STYLE["study"])
    return f"""You are LexiMind, a precise note-taking assistant.

Create structured, well-organized study notes for the topic "{heading}" using ONLY the
information in the context below. Do NOT invent facts or add information not present in the
context. If the context is thin, write fewer bullets rather than speculating. {style}

Do not repeat the heading. Output Markdown only (bullets, bold labels, code/quotes if relevant).

Context:
{context}

Notes on "{heading}":
"""


# AI-assisted editing operations. Each maps to a compact instruction the LLM applies to a
# SELECTION of the user's note (optionally grounded by retrieved context for expand/examples).
NOTE_ASSIST_OPS = {
    "rewrite": "Rewrite the following text to be clearer and better organized. Keep the meaning and any Markdown structure.",
    "expand": "Expand the following text with more detail and depth, staying grounded in the provided context. Keep Markdown formatting.",
    "simplify": "Rewrite the following text in simpler language a beginner can understand, without losing key facts.",
    "grammar": "Fix grammar, spelling, and punctuation in the following text. Return the corrected text only, preserving formatting.",
    "examples": "Generate 1–3 concrete examples that illustrate the following text, grounded in the provided context. Return Markdown bullets.",
    "quiz": "Generate 3–5 quiz questions (with answers) that test understanding of the following text. Format as a Markdown list.",
    "flashcards": "Generate flashcards from the following text as a Markdown list of 'Q: ... / A: ...' pairs.",
    "summarize": "Summarize the following text into a few tight bullet points.",
}

# Which assist ops benefit from retrieval grounding (facts pulled from the workspace).
NOTE_ASSIST_GROUNDED = {"expand", "examples"}


def build_note_assist_prompt(operation: str, selection: str, *, instruction: str | None = None,
                             context: str | None = None) -> str:
    """Assemble the prompt for an AI-assisted edit of a note selection."""
    base = NOTE_ASSIST_OPS.get(operation, NOTE_ASSIST_OPS["rewrite"])
    extra = f"\nAdditional instruction from the user: {instruction}\n" if instruction else ""
    ctx = f"\nGrounding context (use only what is relevant):\n{context}\n" if context else ""
    return f"""You are LexiMind, an expert writing and study assistant.

{base}{extra}{ctx}
Return ONLY the transformed text (Markdown), with no preamble, explanation, or code fences around
the whole answer.

Text:
{selection}

Result:
"""


# --- Module 7: Flashcard generation prompt + parser --------------------------
# Cards are generated in a STRICT, line-delimited format so they parse deterministically. The
# prompt enforces the active-recall quality bar: one concept per card, no ambiguity, concise, with
# a hint — never "split a paragraph into a question".
_CARD_TYPE_GUIDE = {
    "mixed": "Choose the most suitable type per fact (basic, definition, cloze, or truefalse).",
    "basic": "Write question→answer (basic) cards only.",
    "definition": "Write concept→definition cards only.",
    "cloze": "Write cloze-deletion cards only: put the prompt with a blank in Q (use ____ for the blank) and the deleted term in A.",
    "truefalse": "Write true/false cards only: Q is a statement; A is exactly 'True' or 'False' (add a one-line why in H).",
}


def build_flashcard_prompt(card_type_pref: str, n: int, context: str) -> str:
    """Assemble a grounded flashcard-generation prompt for one context window.

    `context` is the Phase-2 engineered context (deduped, ranked, budgeted, compressed) — NOT the
    raw document — so cards stay grounded and their citations map back to retrieved evidence.
    Output MUST be the strict block format parsed by `parse_flashcards`.
    """
    guide = _CARD_TYPE_GUIDE.get(card_type_pref, _CARD_TYPE_GUIDE["mixed"])
    return f"""You are LexiMind, an expert at creating high-quality study flashcards for active recall.

Create up to {n} flashcards from ONLY the information in the context below. {guide}

RULES (critical):
- One single concept per card. No compound or ambiguous questions.
- Questions must be answerable without seeing the context. Be concise and specific.
- Do NOT invent facts. If the context is thin, make fewer cards rather than guessing.
- Always include a short hint that nudges without giving the answer away.
- Do NOT simply copy sentences or split paragraphs — test understanding of the concept.

Output EACH card in EXACTLY this block format, separated by a line with three dashes:

Q: <front of card>
A: <back of card / answer>
H: <a short hint>
T: <one of: basic, definition, cloze, truefalse>
---

Context:
{context}

Flashcards:
"""


def parse_flashcards(raw: str, *, default_type: str = "basic") -> List[Dict[str, Any]]:
    """Parse the strict block format from `build_flashcard_prompt` into card dicts.

    Robust to minor LLM drift: tolerates extra blank lines, missing H/T, and multi-line answers
    up to the next field marker. Cards missing a Q are dropped; a card_type not in the known set
    falls back to `default_type`.
    """
    valid_types = {"basic", "definition", "cloze", "truefalse"}
    cards: List[Dict[str, Any]] = []
    blocks = [b.strip() for b in raw.replace("\r\n", "\n").split("---") if b.strip()]
    for block in blocks:
        front = back = hint = ""
        ctype = default_type
        current = None
        for line in block.split("\n"):
            stripped = line.strip()
            head = stripped[:2].upper()
            if head == "Q:":
                current = "front"; front = stripped[2:].strip()
            elif head == "A:":
                current = "back"; back = stripped[2:].strip()
            elif head == "H:":
                current = "hint"; hint = stripped[2:].strip()
            elif head == "T:":
                current = None
                t = stripped[2:].strip().lower()
                ctype = t if t in valid_types else default_type
            elif current and stripped:
                # continuation of a multi-line field
                if current == "front":
                    front = f"{front} {stripped}".strip()
                elif current == "back":
                    back = f"{back} {stripped}".strip()
                elif current == "hint":
                    hint = f"{hint} {stripped}".strip()
        if not front:
            continue
        if ctype != "cloze" and not back:
            continue  # non-cloze cards need an answer
        cards.append({"front": front[:4000], "back": back[:8000], "hint": hint[:1000], "card_type": ctype})
    return cards


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
