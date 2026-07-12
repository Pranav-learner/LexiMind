"""Adaptive, timestamp-preserving temporal prompt builder (Step 9).

Renders the assembled timeline context into a deterministic prompt whose STRUCTURE adapts to the query
type (transcript / speaker / timeline / topic / scene / timestamp). Every evidence line is tagged with
its [n] citation index AND its timestamp + speaker, so the model is instructed — and able — to answer
with precise timestamps and speaker attributions.

Pure string assembly (no LLM). Returns (system_prompt, user_prompt, citations-echo).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.tretrieval.context import ContextBlock

_SYSTEM = (
    "You are LexiMind's temporal media analyst. Answer ONLY from the timestamped evidence below. "
    "Every claim MUST cite its source with the bracketed index and the timestamp, e.g. "
    "\"...as discussed at 12:04 [3]\". Preserve exact timestamps and attribute statements to the "
    "correct speaker. If the evidence does not contain the answer, say so."
)

# Per-query-type guidance appended to the system prompt (adaptive construction).
_TYPE_GUIDANCE = {
    "timestamp": "The user asked about a specific moment — lead with what happens at that timestamp.",
    "speaker": "The user asked about a speaker — attribute each point to the speaker and cite when they said it.",
    "timeline": "The user asked about ordering/what-happened-next — answer chronologically using the timeline.",
    "topic": "The user asked about a topic/chapter — summarize the relevant span and cite its timestamps.",
    "scene": "The user asked about on-screen content — reference the scene/frame and its timestamp.",
    "transcript": "Answer from the transcript and cite the exact spoken moments.",
}

_MODALITY_LABEL = {
    "transcript": "Transcript", "subtitle": "Subtitle", "timestamp": "Transcript", "speaker": "Speaker",
    "chapter": "Chapter", "topic": "Topic", "event": "Timeline event", "scene": "Scene", "frame": "On-screen text",
}


def _line(b: ContextBlock) -> str:
    label = _MODALITY_LABEL.get(b.modality, b.modality.title())
    who = f" · {b.speaker_label}" if b.speaker_label else ""
    span = b.metadata.get("timespan", "")
    return f"[{b.citation_index}] ({label} {span}{who}) {b.content}".strip()


def build_prompt(query: str, query_type: str, blocks: List[ContextBlock]) -> Tuple[str, str, List[Dict]]:
    guidance = _TYPE_GUIDANCE.get(query_type, _TYPE_GUIDANCE["transcript"])
    system = f"{_SYSTEM}\n{guidance}"

    if not blocks:
        user = (f"Question: {query}\n\n"
                "No timestamped evidence was retrieved for this question. "
                "Tell the user no relevant moment was found.")
        return system, user, []

    # Group by document then chronological (assembly already sorted them).
    lines: List[str] = []
    current_doc = None
    for b in blocks:
        if b.document_id != current_doc:
            current_doc = b.document_id
            lines.append(f"\n--- Recording {current_doc} ---")
        lines.append(_line(b))

    evidence = "\n".join(lines).strip()
    citations = [{"index": b.citation_index, "timespan": b.metadata.get("timespan", ""),
                  "speaker_label": b.speaker_label, "document_id": b.document_id} for b in blocks]

    user = (
        f"Timestamped evidence (chronological):\n{evidence}\n\n"
        f"Question: {query}\n\n"
        "Answer using only the evidence above. Cite every claim with its [index] and timestamp."
    )
    return system, user, citations
