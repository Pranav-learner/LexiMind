"""Learning engines (Steps 6, 7, 8) — Prompt / Retrieval / Agent.

Each implements the `LearningSource` protocol: given the analyzed failure signals + clusters, it emits
explainable `LearningRec`s (reason + evidence + expected_impact + confidence + affected_components). They
NEVER modify prompts / retrieval / agent logic — they only recommend. New learners plug in via the same
protocol.
"""

from __future__ import annotations

from typing import Dict, List

from app.learning.interfaces import FailureCluster, FailureSignal, LearningRec


def _cat_counts(signals: List[FailureSignal]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for s in signals:
        d[s.category] = d.get(s.category, 0) + 1
    return d


def _confidence(count: int, total: int) -> float:
    if total <= 0:
        return 0.3
    return round(min(0.95, 0.4 + 0.5 * (count / total)), 3)


# --------------------------------------------------------------------- Step 6: Prompt Learning
class PromptLearningEngine:
    def analyze(self, signals: List[FailureSignal], clusters: List[FailureCluster]) -> List[LearningRec]:
        counts = _cat_counts(signals)
        total = len(signals) or 1
        recs: List[LearningRec] = []
        halluc = counts.get("hallucination", 0)
        if halluc:
            recs.append(LearningRec(
                category="prompt", title="Tighten grounding instructions in the answer prompt template",
                reason=f"{halluc} hallucination/contradiction signals suggest the prompt under-constrains "
                       "the model to cited evidence.",
                expected_impact="Fewer unsupported claims; higher verification confidence.",
                confidence=_confidence(halluc, total), severity="warning",
                evidence={"hallucination_signals": halluc},
                affected_components=["PromptPackage", "AnswerService"],
                cluster_id=next((c.cluster_id for c in clusters if c.category == "hallucination"), None)))
        neg = counts.get("negative_feedback", 0)
        if neg >= 3:
            recs.append(LearningRec(
                category="prompt", title="A/B a more explicit answer-style prompt version",
                reason=f"{neg} negative feedback items indicate the current prompt version underperforms.",
                expected_impact="Higher thumbs-up rate; promote the winning version, retire the loser.",
                confidence=_confidence(neg, total), severity="info",
                evidence={"negative_feedback": neg},
                affected_components=["PromptPackage"]))
        return recs


# --------------------------------------------------------------------- Step 7: Retrieval Learning
class RetrievalLearningEngine:
    def analyze(self, signals: List[FailureSignal], clusters: List[FailureCluster]) -> List[LearningRec]:
        counts = _cat_counts(signals)
        total = len(signals) or 1
        recs: List[LearningRec] = []
        missing = counts.get("missing_retrieval", 0)
        low = counts.get("low_confidence", 0)
        if missing or low >= 2:
            recs.append(LearningRec(
                category="retrieval", title="Increase retrieval K / enable graph retrieval for weak-recall queries",
                reason=f"{missing} missing-retrieval + {low} low-confidence signals point to recall gaps.",
                expected_impact="Higher recall@k and stronger evidence for grounding.",
                confidence=_confidence(missing + low, total), severity="warning",
                evidence={"missing_retrieval": missing, "low_confidence": low},
                affected_components=["Retrieval Engine", "Semantic Memory"],
                cluster_id=next((c.cluster_id for c in clusters if c.category in ("missing_retrieval", "low_confidence")), None)))
        bad_cite = counts.get("bad_citation", 0)
        if bad_cite:
            recs.append(LearningRec(
                category="retrieval", title="Revisit chunking / citation mapping",
                reason=f"{bad_cite} citation-failure signals suggest chunk boundaries or citation mapping are off.",
                expected_impact="Fewer broken citations; higher citation validity.",
                confidence=_confidence(bad_cite, total), severity="warning",
                evidence={"bad_citation": bad_cite},
                affected_components=["Retrieval Engine", "Context Engineering"]))
        return recs


# --------------------------------------------------------------------- Step 8: Agent Learning
class AgentLearningEngine:
    def analyze(self, signals: List[FailureSignal], clusters: List[FailureCluster]) -> List[LearningRec]:
        counts = _cat_counts(signals)
        total = len(signals) or 1
        recs: List[LearningRec] = []
        agent_fail = counts.get("agent_failure", 0)
        if agent_fail:
            retries = sum(int(s.signals.get("retries", 0)) for s in signals if s.category == "agent_failure")
            recs.append(LearningRec(
                category="agent", title="Review planner / tool-selection for the failing agent workflow",
                reason=f"{agent_fail} agent failures ({retries} cumulative retries) indicate a workflow or "
                       "tool-selection weakness.",
                expected_impact="Higher task success, fewer retries, lower cost/latency.",
                confidence=_confidence(agent_fail, total), severity="critical" if agent_fail >= 3 else "warning",
                evidence={"agent_failures": agent_fail, "cumulative_retries": retries},
                affected_components=["Agent Runtime", "Planner", "Specialized Agents"],
                cluster_id=next((c.cluster_id for c in clusters if c.category == "agent_failure"), None)))
        slow = counts.get("slow_response", 0)
        if slow >= 2:
            recs.append(LearningRec(
                category="routing", title="Adjust model routing / policy for slow queries",
                reason=f"{slow} slow-response signals; a faster policy or lighter model may suffice.",
                expected_impact="Lower latency at comparable quality.",
                confidence=_confidence(slow, total), severity="info",
                evidence={"slow_responses": slow}, affected_components=["Optimization Platform", "Model Router"]))
        return recs
