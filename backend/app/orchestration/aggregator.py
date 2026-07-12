"""Result Aggregator (Step 7) — merge the team's outputs into ONE grounded deliverable.

Takes the completed agent results and:
- merges + de-duplicates evidence (re-indexed) and citations,
- combines the per-agent verification reports into one workflow-level confidence/status,
- assembles ONE unified `PromptPackage` (numbered merged evidence + each agent's deliverable) and makes
  exactly ONE `answer_fn` call — the SINGLE AnswerService pathway — to synthesize the final narrative.

The orchestrator makes N agent calls (each already funnelled through AnswerService) plus this ONE final
synthesis; no second inference pipeline is created and no agent output bypasses AnswerService.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents.prompt_package import PromptPackage, PromptSection
from app.agents.specialized.outputs import StructuredOutput


def _merge_evidence(results: List[Any], *, limit: int = 30) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for res in results:
        for e in getattr(res, "evidence", []) or []:
            d = e.to_dict() if hasattr(e, "to_dict") else dict(e)
            key = (d.get("document_id"), (d.get("text") or "")[:80], d.get("timespan"))
            if key in seen or not (d.get("text") or "").strip():
                continue
            seen.add(key)
            merged.append(d)
    merged.sort(key=lambda d: d.get("score", 0.0), reverse=True)
    merged = merged[:limit]
    for i, d in enumerate(merged, start=1):
        d["index"] = i
    return merged


def _combined_verification(results: List[Any]) -> Dict[str, Any]:
    reports = [getattr(r, "verification", None) for r in results if getattr(r, "verification", None)]
    reports = [r for r in reports if isinstance(r, dict) and "confidence" in r]
    if not reports:
        return {"status": "unknown", "confidence": None, "reports": 0}
    confs = [r["confidence"]["overall"] for r in reports if r.get("confidence")]
    worst = "verified"
    for r in reports:
        s = r.get("status")
        if s == "failed":
            worst = "failed"; break
        if s == "warning" and worst != "failed":
            worst = "warning"
    return {
        "status": worst,
        "confidence": round(sum(confs) / len(confs), 4) if confs else None,
        "reports": len(reports),
        "contradictions": sum(len(r.get("contradictions", [])) for r in reports),
        "warnings": sum(len(r.get("warnings", [])) for r in reports),
    }


class ResultAggregator:
    name = "aggregator-v1"

    _SYSTEM = (
        "You are LexiMind's orchestration synthesizer. Several specialized agents each produced a "
        "deliverable for the objective. Write ONE cohesive, non-repetitive final answer that integrates "
        "their findings, grounded ONLY in the numbered evidence. Cite claims with [n] markers, note any "
        "disagreements between the agents, and do not invent facts."
    )

    def aggregate(self, objective: str, results: List[Any], *, answer_fn=None) -> Dict[str, Any]:
        results = [r for r in results if r is not None and getattr(r, "success", False)]
        merged_ev = _merge_evidence(results)
        combined_ver = _combined_verification(results)

        # ---- ONE unified PromptPackage → ONE AnswerService call ----
        pkg = PromptPackage(query=objective or "Synthesize the team's findings.")
        pkg.system = self._SYSTEM
        if merged_ev:
            body = "\n".join(f"[{d['index']}] {(d.get('text') or '')}" for d in merged_ev)
            pkg.sections.append(PromptSection(title="Evidence", content=body))
        for res in results:
            out = res.output.to_dict() if res.output is not None else {}
            deliverable = (out.get("summary") or "") + "\n" + _first_markdown(out)
            pkg.sections.append(PromptSection(title=f"Deliverable from {res.agent}",
                                              content=deliverable.strip()[:2500]))
        pkg.citations = merged_ev
        final_answer = ""
        llm_calls = 0
        if answer_fn is not None and (results or objective):
            final_answer = (answer_fn(pkg.render()) or "").strip()
            llm_calls = 1

        # ---- unified structured deliverable ----
        out = StructuredOutput(title=f"Orchestrated result: {_short(objective)}",
                               summary=_first_line(final_answer) or "Synthesized multi-agent result.")
        out.heading("Objective", 2).markdown(objective or "")
        if final_answer:
            out.heading("Synthesis", 2).markdown(final_answer)
        out.heading("Agent Deliverables", 2)
        out.table(["Agent", "Deliverable", "Summary"],
                  [[r.agent, (r.output.title if r.output else ""),
                    (r.output.summary if r.output else "")[:120]] for r in results])
        if combined_ver.get("confidence") is not None:
            out.callout(f"Combined verification: {combined_ver['status']} · "
                        f"confidence {combined_ver['confidence']:.0%} across {combined_ver['reports']} report(s).")
        out.add_citations(merged_ev).citations_section()

        return {
            "answer": final_answer,
            "output": out.to_dict(),
            "citations": merged_ev,
            "combined_verification": combined_ver,
            "llm_calls": llm_calls,
            "prompt_package": pkg.to_dict(),
            "agents_merged": [r.agent for r in results],
        }


def _first_markdown(output: Dict[str, Any]) -> str:
    for b in (output.get("blocks") or []):
        if b.get("type") == "markdown":
            return str(b.get("content") or "")
    return ""


def _first_line(s: str) -> str:
    for line in (s or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:200]
    return ""


def _short(s: str, n: int = 80) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"
