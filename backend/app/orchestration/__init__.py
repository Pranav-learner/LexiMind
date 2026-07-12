"""Multi-Agent Orchestration Platform (Phase 6, Module 4) — the Phase-6 capstone.

Turns LexiMind's specialized agents into a coordinated TEAM: a user objective is decomposed into a task
graph, governed, scheduled (with parallelism/retry/timeout/fallback/graceful degradation), executed by
the existing per-agent pathway (`AgentTaskService.run_task`, which already reuses retrieval → context →
PromptPackage → AnswerService → verification), reused via a shared context (no duplicate retrieval), and
merged by a Result Aggregator into ONE unified PromptPackage → ONE final AnswerService call, then
verified. It creates NO new AI pipeline — it composes Modules 1–3.

    interfaces.py     TaskNode/TaskGraph/OrchestrationPlan/AgentMessage + Protocols
    planner.py        TaskPlanner — objective → task graph (heuristic decomposition)
    registry.py       declarative workflow templates
    governance.py     GovernancePolicy — quotas, depth/loop guards, permissions
    bus.py            CommunicationBus — structured inter-agent messages (no chain-of-thought)
    shared_context.py SharedContextManager — evidence reuse across agents
    scheduler.py      AgentScheduler — layered exec + retry/timeout/fallback/recovery
    aggregator.py     ResultAggregator — merge → ONE PromptPackage → ONE AnswerService call
    orchestrator.py   Orchestrator — plan → govern → schedule → aggregate → verify
    models/repository/service/schemas/api  OrchestrationExecutionLog + coordination + DTOs + routes
"""
