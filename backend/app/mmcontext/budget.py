"""Adaptive token budget manager (Step 5) — allocate the context window across modalities by intent.

Phase-2 budgeted one text stream; this adaptively splits the budget across modalities using the
query-intent weights (a visual question gives images/diagrams more budget; a technical one gives text
more), then greedily fills each modality's allowance by evidence score — compressing an item to fit
when possible, and redistributing leftover budget in a final global pass. The TOTAL is a hard ceiling
that is never exceeded.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from app.context.tokenizer import heuristic_token_count
from app.mmcontext.schemas import MMEvidence


def allocate(modality_weights: Dict[str, float], present: List[str], total: int) -> Dict[str, int]:
    """Split `total` tokens across the present modalities proportional to their intent weights."""
    weights = {m: modality_weights.get(m, 0.5) for m in present}
    s = sum(weights.values()) or 1.0
    return {m: int(total * w / s) for m, w in weights.items()}


def manage(ranked: List[MMEvidence], modality_weights: Dict[str, float], total: int,
           *, compress: bool = True, compress_fn: Callable[[MMEvidence, int], str] = None
           ) -> Tuple[List[MMEvidence], List[dict], Dict[str, int]]:
    """Select evidence within budget. Returns (included, dropped[{key,reason}], used_per_modality)."""
    present = sorted({e.modality for e in ranked})
    alloc = allocate(modality_weights, present, total)
    used: Dict[str, int] = {m: 0 for m in present}
    used_total = 0
    included: List[MMEvidence] = []
    deferred: List[MMEvidence] = []

    def _try(ev: MMEvidence, cap: int) -> bool:
        nonlocal used_total
        cost = heuristic_token_count(ev.content)
        remaining_modality = alloc[ev.modality] - used[ev.modality]
        remaining_total = total - used_total
        limit = min(cap, remaining_modality, remaining_total)
        if cost <= limit:
            ev.token_cost = cost
        elif compress and compress_fn is not None and limit > 20:
            ev.original_tokens = cost
            ev.content = compress_fn(ev, limit)
            ev.compressed = True
            ev.token_cost = heuristic_token_count(ev.content)
            if ev.token_cost > min(alloc[ev.modality] - used[ev.modality], total - used_total):
                return False
        else:
            return False
        ev.included = True
        ev.selection_reason = ("compressed to fit" if ev.compressed else "fits budget") + f" (modality {ev.modality})"
        used[ev.modality] += ev.token_cost
        used_total += ev.token_cost
        included.append(ev)
        return True

    # Pass 1 — fill each modality's allocation, globally ordered by evidence score.
    for ev in ranked:
        if not _try(ev, alloc[ev.modality]):
            deferred.append(ev)

    # Pass 2 — redistribute leftover TOTAL budget to the best deferred items (ignore modality caps).
    dropped: List[dict] = []
    for ev in deferred:
        remaining_total = total - used_total
        if remaining_total <= 20:
            dropped.append({"key": ev.key, "modality": ev.modality, "reason": "exceeded token budget"})
            continue
        cost = heuristic_token_count(ev.content)
        if cost <= remaining_total:
            ev.token_cost = cost
        elif compress and compress_fn is not None:
            ev.original_tokens = ev.original_tokens or cost
            ev.content = compress_fn(ev, remaining_total)
            ev.compressed = True
            ev.token_cost = heuristic_token_count(ev.content)
        if ev.token_cost and used_total + ev.token_cost <= total:
            ev.included = True
            ev.selection_reason = "included via budget redistribution"
            used[ev.modality] = used.get(ev.modality, 0) + ev.token_cost
            used_total += ev.token_cost
            included.append(ev)
        else:
            dropped.append({"key": ev.key, "modality": ev.modality, "reason": "exceeded token budget"})

    return included, dropped, used
