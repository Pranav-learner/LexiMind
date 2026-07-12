"""Unit tests for the Phase-6 Module-4 Multi-Agent Orchestration platform — pure/offline (no HTTP, no LLM).

Covers task decomposition, the task graph (layers/serialize/cycle), governance, the communication bus,
the shared context manager, the scheduler (dependency gating / retry / fallback / optional / recovery),
and the result aggregator (merge + single answer_fn call).
"""

from __future__ import annotations

from app.agents.specialized.base import Evidence
from app.agents.specialized.outputs import StructuredOutput
from app.orchestration.aggregator import ResultAggregator, _merge_evidence
from app.orchestration.bus import CommunicationBus
from app.orchestration.errors import GovernanceError
from app.orchestration.governance import GovernancePolicy
from app.orchestration.interfaces import (
    FAILED, OK, RECOVERED, SKIPPED, TaskGraph, TaskNode,
)
from app.orchestration.planner import TaskPlanner
from app.orchestration.registry import get_template, list_templates
from app.orchestration.scheduler import AgentScheduler
from app.orchestration.shared_context import SharedContextManager


# --------------------------------------------------------------------- planner
def test_planner_decomposes_compare_and_study():
    plan = TaskPlanner().decompose("Compare these papers and make a study guide",
                                   document_ids=["d1", "d2"], params={})
    ids = [n.id for n in plan.graph.nodes]
    assert "research" in ids and "comparison" in ids and "study" in ids and "verification" in ids
    layers = [[n.id for n in L] for L in plan.graph.layers()]
    assert layers[0] == ["research"]                        # research first (evidence base)
    # comparison + study run in parallel after research
    assert "comparison" in layers[1] and "study" in layers[1]


def test_planner_simple_research_write():
    plan = TaskPlanner().decompose("Research memory management and write a report", document_ids=[], params={})
    ids = [n.id for n in plan.graph.nodes]
    assert ids[0] == "research" and "writing" in ids
    writing = plan.graph.by_id("writing")
    assert writing.depends_on == ["research"] and writing.forward_evidence is True


# --------------------------------------------------------------------- task graph
def test_task_graph_layers_and_serialization():
    g = TaskGraph()
    g.add(TaskNode(id="a", agent="research"))
    g.add(TaskNode(id="b", agent="writing", depends_on=["a"], priority=2))
    g.add(TaskNode(id="c", agent="study", depends_on=["a"], priority=1))
    layers = [[n.id for n in L] for L in g.layers()]
    assert layers[0] == ["a"] and set(layers[1]) == {"b", "c"}
    assert layers[1][0] == "c"                              # higher priority (1) first within the layer
    assert g.depth() == 2 and g.max_width() == 2
    g2 = TaskGraph.from_dict(g.to_dict())
    assert [n.id for n in g2.nodes] == ["a", "b", "c"] and g2.by_id("b").depends_on == ["a"]


# --------------------------------------------------------------------- governance
def test_governance_rejects_cycle_self_dep_and_unknown():
    gov = GovernancePolicy()
    cycle = TaskGraph(nodes=[TaskNode(id="a", agent="research", depends_on=["b"]),
                             TaskNode(id="b", agent="writing", depends_on=["a"])])
    for bad in [
        cycle,
        TaskGraph(nodes=[TaskNode(id="a", agent="research", depends_on=["a"])]),
        TaskGraph(nodes=[TaskNode(id="a", agent="research", depends_on=["x"])]),
        TaskGraph(nodes=[TaskNode(id="a", agent="hacker")]),
    ]:
        try:
            gov.validate(bad); assert False, "expected GovernanceError"
        except GovernanceError:
            pass


def test_governance_quota():
    gov = GovernancePolicy(max_nodes=3)
    big = TaskGraph(nodes=[TaskNode(id=f"n{i}", agent="research") for i in range(4)])
    try:
        gov.validate(big); assert False
    except GovernanceError as e:
        assert "quota" in str(e)


# --------------------------------------------------------------------- communication bus
def test_bus_records_structured_messages():
    bus = CommunicationBus()
    bus.task_request("research", "research", "obj")
    bus.result("research", "research", task_id="agt_1", summary="done", evidence=3, confidence=0.8)
    bus.error("writing", "boom", recovered=True)
    tl = bus.timeline()
    assert [m["type"] for m in tl] == ["task_request", "result", "error"]
    assert tl[0]["seq"] == 1 and tl[1]["payload"]["task_id"] == "agt_1"


# --------------------------------------------------------------------- shared context
class _FakeResult:
    def __init__(self, agent, evidence, verification=None, success=True):
        self.agent = agent; self.success = success; self.evidence = evidence
        self.verification = verification; self.token_usage = 5; self.estimated_cost = 1.0
        self.output = StructuredOutput(title=f"{agent} out", summary=f"{agent} summary").markdown("body")


def _ev(i, text, doc="d1", score=0.8):
    return Evidence(index=i, text=text, origin_tool="workspace_search", document_id=doc, score=score)


def test_shared_context_forwards_dependency_evidence():
    shared = SharedContextManager()
    shared.put_result("research", _FakeResult("research", [_ev(1, "alpha fact"), _ev(2, "beta fact")]))
    node = TaskNode(id="writing", agent="writing", depends_on=["research"])
    dep_ev = shared.dependency_evidence(node)
    assert len(dep_ev) == 2 and dep_ev[0]["text"].startswith("alpha")
    assert len(shared.all_evidence()) == 2


# --------------------------------------------------------------------- scheduler
def _runner(outcomes):
    """Build a run_node that returns outcomes keyed by node id (dict id -> ok bool or 'fail_then_ok')."""
    calls = {}

    def run_node(node, agent):
        calls[node.id] = calls.get(node.id, 0) + 1
        spec = outcomes.get(node.id, True)
        if spec == "fail_then_ok":
            ok = calls[node.id] >= 2
        elif spec == "fallback_only":
            ok = agent != node.agent           # only the fallback agent succeeds
        else:
            ok = bool(spec)
        return {"ok": ok, "task_id": f"t_{node.id}", "summary": "s", "evidence": 1,
                "error": None if ok else "failed"}
    run_node.calls = calls
    return run_node


def test_scheduler_runs_in_dependency_order():
    g = TaskGraph(nodes=[TaskNode(id="a", agent="research"),
                         TaskNode(id="b", agent="writing", depends_on=["a"])])
    bus = CommunicationBus()
    summary = AgentScheduler().run(g, run_node=_runner({}), bus=bus)
    assert g.by_id("a").status == OK and g.by_id("b").status == OK
    assert summary["completed"] == 2 and summary["order"] == ["a", "b"]


def test_scheduler_skips_dependents_of_failed_required_node():
    g = TaskGraph(nodes=[TaskNode(id="a", agent="research"),
                         TaskNode(id="b", agent="writing", depends_on=["a"])])
    bus = CommunicationBus()
    AgentScheduler().run(g, run_node=_runner({"a": False}), bus=bus)
    assert g.by_id("a").status == FAILED and g.by_id("b").status == SKIPPED


def test_scheduler_optional_failure_does_not_cascade_as_failed():
    g = TaskGraph(nodes=[TaskNode(id="a", agent="research"),
                         TaskNode(id="opt", agent="study", depends_on=["a"], optional=True)])
    bus = CommunicationBus()
    s = AgentScheduler().run(g, run_node=_runner({"opt": False}), bus=bus)
    assert g.by_id("opt").status == SKIPPED and s["failed"] == 0


def test_scheduler_retry_and_fallback():
    g = TaskGraph(nodes=[TaskNode(id="r", agent="research", retries=2)])
    AgentScheduler().run(g, run_node=_runner({"r": "fail_then_ok"}), bus=CommunicationBus())
    assert g.by_id("r").status == OK and g.by_id("r").attempts == 2

    g2 = TaskGraph(nodes=[TaskNode(id="w", agent="writing", retries=1, fallback="research")])
    AgentScheduler().run(g2, run_node=_runner({"w": "fallback_only"}), bus=CommunicationBus())
    assert g2.by_id("w").status == RECOVERED and g2.by_id("w").recovered_by == "research"


# --------------------------------------------------------------------- aggregator
def test_merge_evidence_dedupes_and_reindexes():
    r1 = _FakeResult("research", [_ev(1, "shared fact", doc="d1", score=0.9)])
    r2 = _FakeResult("writing", [_ev(1, "shared fact", doc="d1", score=0.9), _ev(2, "new fact", score=0.4)])
    merged = _merge_evidence([r1, r2])
    assert len(merged) == 2 and [m["index"] for m in merged] == [1, 2]
    assert merged[0]["text"] == "shared fact"              # highest score first


def test_aggregator_single_answer_call_and_combined_verification():
    calls = {"n": 0}
    def fake_fn(prompt): calls["n"] += 1; return "UNIFIED SYNTHESIS"
    ver = {"status": "warning", "confidence": {"overall": 0.6}, "contradictions": [], "warnings": ["w"]}
    results = [_FakeResult("research", [_ev(1, "a")], verification=ver),
               _FakeResult("writing", [_ev(2, "b")], verification={"status": "verified",
                           "confidence": {"overall": 0.9}, "contradictions": [], "warnings": []})]
    agg = ResultAggregator().aggregate("objective", results, answer_fn=fake_fn)
    assert calls["n"] == 1 and agg["llm_calls"] == 1        # exactly ONE AnswerService call
    assert agg["answer"] == "UNIFIED SYNTHESIS"
    assert agg["combined_verification"]["status"] == "warning"   # worst-of
    assert 0.7 <= agg["combined_verification"]["confidence"] <= 0.8
    assert any(b["type"] == "table" for b in agg["output"]["blocks"])


# --------------------------------------------------------------------- registry
def test_templates_are_valid_graphs():
    names = {t["name"] for t in list_templates()}
    assert {"research_report", "compare_and_report", "study_pipeline", "full_research_suite"} <= names
    for name in names:
        GovernancePolicy().validate(get_template(name))     # every template passes governance
