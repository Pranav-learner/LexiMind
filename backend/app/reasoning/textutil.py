"""Deterministic text primitives for the Verification & Reasoning Engine (Phase 6, Module 3).

Kept pure + dependency-free (no LLM, no torch) so the whole verification pipeline is instant, testable
and reproducible. These are the measurable signals the evidence/contradiction/citation validators build
on: keyword extraction, lexical overlap (coverage + Jaccard), negation detection, and numeric-claim
extraction. A future embedding/NLI backend can implement richer versions behind the same call sites.
"""

from __future__ import annotations

import re
from typing import List, Set, Tuple

_WORD = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")
_NUM = re.compile(r"-?\d+(?:\.\d+)?%?")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

_STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "so", "of", "to", "in", "on", "for",
    "with", "as", "by", "at", "from", "into", "is", "are", "was", "were", "be", "been", "being", "it",
    "its", "this", "that", "these", "those", "there", "here", "which", "who", "whom", "whose", "what",
    "when", "where", "why", "how", "can", "could", "should", "would", "may", "might", "will", "shall",
    "do", "does", "did", "has", "have", "had", "not", "no", "yes", "we", "you", "they", "he", "she",
    "i", "me", "my", "our", "your", "their", "his", "her", "them", "us", "also", "such", "some", "any",
    "all", "each", "more", "most", "other", "only", "own", "same", "very", "just", "about", "over",
    "between", "both", "because", "while", "during", "above", "below", "up", "down", "out", "off",
}

_NEGATIONS: Set[str] = {
    "not", "no", "never", "none", "cannot", "can't", "cant", "won't", "wont", "doesn't", "doesnt",
    "don't", "dont", "isn't", "isnt", "aren't", "arent", "wasn't", "wasnt", "weren't", "werent",
    "without", "neither", "nor", "unable", "fails", "fail", "false", "incorrect", "impossible",
}

# lightweight antonym pairs — enough to catch obvious factual conflicts deterministically
_ANTONYMS: List[Tuple[str, str]] = [
    ("increase", "decrease"), ("increases", "decreases"), ("higher", "lower"), ("more", "less"),
    ("faster", "slower"), ("larger", "smaller"), ("greater", "lesser"), ("true", "false"),
    ("enable", "disable"), ("enabled", "disabled"), ("allow", "prevent"), ("before", "after"),
    ("above", "below"), ("positive", "negative"), ("success", "failure"), ("valid", "invalid"),
    ("safe", "unsafe"), ("stable", "unstable"), ("synchronous", "asynchronous"),
]


def tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD.findall(text or "")]


def keywords(text: str) -> Set[str]:
    """Content words (lowercased, stopword- and pure-number-stripped) — the unit of overlap."""
    out: Set[str] = set()
    for t in tokens(text):
        if t in _STOPWORDS or t in _NEGATIONS:
            continue
        if t.isdigit():
            continue
        if len(t) <= 1:
            continue
        out.add(t)
    return out


def coverage(claim: str, evidence: str) -> float:
    """Fraction of the claim's keywords present in the evidence (directional recall of the claim)."""
    ck = keywords(claim)
    if not ck:
        return 0.0
    ek = keywords(evidence)
    return len(ck & ek) / len(ck)


def jaccard(a: str, b: str) -> float:
    ka, kb = keywords(a), keywords(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


def has_negation(text: str) -> bool:
    return bool(_NEGATIONS & set(tokens(text)))


def negation_count(text: str) -> int:
    toks = tokens(text)
    return sum(1 for t in toks if t in _NEGATIONS)


def numbers(text: str) -> List[str]:
    return _NUM.findall(text or "")


def _negated_keywords(toks: List[str], shared: Set[str], *, window: int = 3) -> Set[str]:
    """Shared content keywords that sit within `window` tokens AFTER a negation ("not safe" → {safe})."""
    out: Set[str] = set()
    neg_at = -10
    for i, t in enumerate(toks):
        if t in _NEGATIONS:
            neg_at = i
        elif t in shared and 0 < (i - neg_at) <= window:
            out.add(t)
    return out


def polarity_conflict(a: str, b: str) -> bool:
    """True if two texts about the same subject disagree in polarity.

    Precise (avoids false positives from incidental negations like "no preemption"): a conflict needs
    (1) an explicit antonym pair across the two, OR (2) a SHARED keyword negated in exactly one text
    ("X is safe" vs "X is not safe"). Incidental negations that don't attach to a shared keyword are
    ignored. Callers still gate on subject overlap first.
    """
    ta, tb = tokens(a), tokens(b)
    sa, sb = set(ta), set(tb)
    for x, y in _ANTONYMS:
        if (x in sa and y in sb) or (y in sa and x in sb):
            return True
    shared = keywords(a) & keywords(b)
    if not shared:
        return False
    neg_a = _negated_keywords(ta, shared)
    neg_b = _negated_keywords(tb, shared)
    return bool(neg_a ^ neg_b)   # a shared keyword negated in one side but not the other


def numeric_conflict(a: str, b: str) -> bool:
    """True if both texts carry numbers about the same subject but the number sets differ."""
    na, nb = set(numbers(a)), set(numbers(b))
    if not na or not nb:
        return False
    return na != nb and not (na & nb)


def sentences(text: str) -> List[str]:
    """Split prose into sentences (also treats explicit newlines as boundaries)."""
    out: List[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        for s in _SENT_SPLIT.split(line):
            s = s.strip()
            if s:
                out.append(s)
    return out
