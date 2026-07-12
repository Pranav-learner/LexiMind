"""Unit tests for the Agent Framework internals — pure/offline (no LLM, no HTTP).

Covers the planner, execution graph (serialize + layering), tool + agent registries, the tool executor
(permission gate + retry + conditional + failure policy), the permission manager, memory, and the
prompt package. Uses tiny fake tools so no service/DB is touched.
"""

from __future__ import annotations

from app.agents.executor import ToolExecutor
from app.agents.graph import ExecutionGraph, GraphNode
from app.agents.interfaces import ToolResult, ToolSpec
from app.agents.memory import MemoryManager
from app.agents.permissions import PermissionManager
from app.agents.planner import HeuristicPlanner
from app.agents.prompt_package import PromptPackage
from app.agents.registry import agent_registry, tool_registry


# --------------------------------------------------------------------- planner
class _PCtx:
    def __init__(self, q, doc=None):
        self.query = q; self.document_id = doc; self.owner_id = "o"; self.db = None


def test_planner_routes_generation_intents():
    assert [n.tool for n in HeuristicPlanner().plan(_PCtx("make flashcards")).graph.nodes] == ["generate_flashcards"]
    assert [n.tool for n in HeuristicPlanner().plan(_PCtx("summarize this")).graph.nodes] == ["generate_summary"]
    assert [n.tool for n in HeuristicPlanner().plan(_PCtx("take study notes")).graph.nodes] == ["generate_notes"]


def test_planner_qa_adds_temporal_on_media_cue():
    plain = HeuristicPlanner().plan(_PCtx("what is a mutex"))
    assert [n.tool for n in plain.graph.nodes] == ["workspace_search"]
    media = HeuristicPlanner().plan(_PCtx("what did the speaker say in the lecture"))
    assert set(n.tool for n in media.graph.nodes) == {"workspace_search", "temporal_search"}
    assert media.requires_tools and media.estimated_cost > 0


def test_planner_greeting_needs_no_tools():
    p = HeuristicPlanner().plan(_PCtx("hello"))
    assert p.requires_tools is False and not p.graph.nodes


# --------------------------------------------------------------------- graph
def test_graph_serialization_roundtrip():
    g = ExecutionGraph()
    g.add(GraphNode(id="a", tool="workspace_search"))
    g.add(GraphNode(id="b", tool="temporal_search", depends_on=["a"]))
    d = g.to_dict()
    g2 = ExecutionGraph.from_dict(d)
    assert [n.id for n in g2.nodes] == ["a", "b"]
    assert g2.nodes[1].depends_on == ["a"]


def test_graph_layers_orders_dependencies():
    g = ExecutionGraph()
    g.add(GraphNode(id="a", tool="t"))
    g.add(GraphNode(id="b", tool="t"))
    g.add(GraphNode(id="c", tool="t", depends_on=["a", "b"]))
    layers = g.layers()
    assert {n.id for n in layers[0]} == {"a", "b"}
    assert [n.id for n in layers[1]] == ["c"]


def test_graph_detects_cycle():
    g = ExecutionGraph()
    g.add(GraphNode(id="a", tool="t", depends_on=["b"]))
    g.add(GraphNode(id="b", tool="t", depends_on=["a"]))
    try:
        g.layers()
        assert False, "expected a cycle error"
    except ValueError:
        pass


# --------------------------------------------------------------------- registries
def test_tool_registry_discovery_and_specs():
    reg = tool_registry()
    names = {s.name for s in reg.specs()}
    assert {"workspace_search", "temporal_search", "generate_summary"} <= names
    assert reg.has("workspace_search")
    assert reg.spec("generate_summary").permissions == ["generate", "write"]


def test_agent_registry_has_workspace_agent_and_planned_agents():
    agents = {a.name: a for a in agent_registry().all()}
    assert agents["workspace_agent"].implemented is True
    assert agents["research_agent"].implemented is False and agents["research_agent"].status == "planned"


# --------------------------------------------------------------------- executor (fake tools)
class _FakeTool:
    def __init__(self, name, *, ok=True, perms=None, fail_times=0, parallel=True):
        self.spec = ToolSpec(name=name, permissions=perms or ["search"], parallel_safe=parallel)
        self._ok = ok; self._fail_times = fail_times; self.calls = 0

    def execute(self, ctx, args):
        self.calls += 1
        if self.calls <= self._fail_times:
            return ToolResult(tool=self.spec.name, ok=False, error="transient")
        return ToolResult(tool=self.spec.name, ok=self._ok, output={"n": self.calls},
                          context_text=f"{self.spec.name} evidence" if self._ok else "")


class _FakeReg:
    def __init__(self, tools):
        self._t = {t.spec.name: t for t in tools}

    def get(self, name):
        return self._t[name]

    def spec(self, name):
        return self._t[name].spec


class _Ctx:
    def __init__(self):
        self.services = {}; self._cancelled = False


def test_executor_runs_and_collects():
    tool = _FakeTool("workspace_search")
    ex = ToolExecutor(_FakeReg([tool]), PermissionManager(["search"]))
    g = ExecutionGraph(); g.add(GraphNode(id="a", tool="workspace_search"))
    res = ex.run_graph(g, _Ctx())
    assert res["a"].ok and g.by_id("a").status == "ok"


def test_executor_denies_without_permission():
    tool = _FakeTool("generate_summary", perms=["generate", "write"])
    ex = ToolExecutor(_FakeReg([tool]), PermissionManager(["search"]))  # only search granted
    g = ExecutionGraph(); g.add(GraphNode(id="g", tool="generate_summary"))
    res = ex.run_graph(g, _Ctx())
    assert res["g"].ok is False and g.by_id("g").status == "denied"
    assert tool.calls == 0  # never executed


def test_executor_retries_transient_failure():
    tool = _FakeTool("workspace_search", fail_times=1)
    ex = ToolExecutor(_FakeReg([tool]), PermissionManager(["search"]))
    g = ExecutionGraph(); g.add(GraphNode(id="a", tool="workspace_search", retries=2))
    res = ex.run_graph(g, _Ctx())
    assert res["a"].ok and res["a"].retries == 1 and g.by_id("a").attempts == 2


def test_executor_conditional_skip():
    empty = _FakeTool("workspace_search", ok=True)
    empty.execute = lambda ctx, args: ToolResult(tool="workspace_search", ok=True, output={}, context_text="")
    dep = _FakeTool("temporal_search")
    ex = ToolExecutor(_FakeReg([empty, dep]), PermissionManager(["search"]))
    g = ExecutionGraph()
    g.add(GraphNode(id="a", tool="workspace_search"))
    g.add(GraphNode(id="b", tool="temporal_search", depends_on=["a"], condition="has_results:a"))
    ex.run_graph(g, _Ctx())
    assert g.by_id("b").status == "skipped" and dep.calls == 0


def test_executor_abort_on_failure_policy():
    bad = _FakeTool("workspace_search", ok=False)
    after = _FakeTool("temporal_search")
    ex = ToolExecutor(_FakeReg([bad, after]), PermissionManager(["search"]))
    g = ExecutionGraph()
    g.add(GraphNode(id="a", tool="workspace_search", on_failure="abort", retries=1))
    g.add(GraphNode(id="b", tool="temporal_search", depends_on=["a"]))
    ex.run_graph(g, _Ctx())
    assert g.by_id("a").status == "failed" and g.by_id("b").status == "cancelled"
    assert after.calls == 0


# --------------------------------------------------------------------- permissions / memory / prompt
def test_permission_manager():
    pm = PermissionManager(["search"])
    ok, _ = pm.allows(ToolSpec(name="x", permissions=["search"]), None)
    assert ok
    denied, reason = pm.allows(ToolSpec(name="y", permissions=["write"]), None)
    assert not denied and "write" in reason
    scoped = PermissionManager(["search", "write"], allowed_tools=["workspace_search"])
    assert scoped.allows(ToolSpec(name="other", permissions=["search"]), None)[0] is False


def test_memory_scopes():
    m = MemoryManager()
    m.put("scratchpad", "k", 1)
    m.record_tool("node_a", ToolResult(tool="t"))
    assert m.get("scratchpad", "k") == 1
    assert len(m.tool_outputs()) == 1
    assert "node_a" in m.snapshot()["execution"]


def test_prompt_package_render():
    pkg = PromptPackage(query="what is x?")
    pkg.add_tool_evidence("workspace_search", ToolResult(tool="workspace_search", ok=True,
                                                         context_text="X is a thing",
                                                         citations=[{"index": 1}]))
    rendered = pkg.render()
    assert "Evidence from workspace_search" in rendered and "Request: what is x?" in rendered
    assert len(pkg.citations) == 1 and pkg.to_dict()["citation_count"] == 1
