"""Claim extraction (Step 3 input) — turn a draft answer into checkable claims.

Deterministic + LLM-free: splits the answer's prose into sentences/bullets, drops non-claims
(headings, table rows, code, boilerplate), and parses the `[n]` citation markers each claim carries.
A "claim" is an important, verifiable statement — the unit the evidence validator rules on. A future
LLM/NLI claim segmenter can replace this behind the `ClaimExtractor` protocol.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from app.reasoning.interfaces import Claim
from app.reasoning.textutil import keywords, sentences

_CITE = re.compile(r"\[(\d+)\]")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s+")
_TABLE = re.compile(r"^\s*\|")
_BOLD_LABEL = re.compile(r"^\s*\*\*[^*]+\*\*\s*[:—-]")


def _strip_markdown(line: str) -> str:
    line = _BULLET.sub("", line)
    line = re.sub(r"[*_`>]+", "", line)
    return line.strip()


class SentenceClaimExtractor:
    name = "sentence-v1"

    def extract(self, answer_text: str, *, sections: Optional[Dict[str, str]] = None) -> List[Claim]:
        claims: List[Claim] = []
        current_section = ""
        idx = 0
        in_code = False
        for raw in (answer_text or "").split("\n"):
            line = raw.rstrip()
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code or not line.strip():
                continue
            if _HEADING.match(line):
                current_section = _HEADING.sub("", line).strip()
                continue
            if _TABLE.match(line):
                continue
            body = _strip_markdown(line)
            # split a prose line into sentences; bullets are usually single claims
            parts = sentences(body) if not _BULLET.match(line) else [body]
            for part in parts:
                text = part.strip()
                if not self._is_claim(text):
                    continue
                cites = [int(m) for m in _CITE.findall(text)]
                idx += 1
                claims.append(Claim(id=f"c{idx}", text=text, section=current_section,
                                    citation_indices=cites, important=True))
        return claims

    @staticmethod
    def _is_claim(text: str) -> bool:
        """Filter out non-claims: too short, no content words, or pure labels/questions."""
        if len(text) < 12:
            return False
        if text.endswith("?"):
            return False
        if len(keywords(text)) < 2:
            return False
        if _BOLD_LABEL.match(text):
            return False
        # drop meta lines the agents emit
        low = text.lower()
        if low.startswith(("citation", "evidence", "reference", "note:", "source")):
            return False
        return True
