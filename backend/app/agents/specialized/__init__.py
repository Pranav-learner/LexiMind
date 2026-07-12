"""Specialized Research & Writing Agents (Phase 6, Module 2).

Autonomous, multi-step workers built ON the Module-1 Agent framework — they turn the runtime from an
AI *chatbot* into an AI *employee*. Each agent encapsulates domain-specific planning + orchestration
(plan → research → analysis → write) and DELEGATES retrieval, context engineering, prompt building and
inference to the existing shared infrastructure (Phase-1/2/4/5 retrieval + the single `AnswerService`).
No second retrieval/prompt/LLM pipeline is created.

    base.py           SpecializedAgent interface + AgentTask/Evidence/AgentTaskResult + reusable helpers
    outputs.py        StructuredOutput — the citation-preserving, multi-format deliverable
    task_memory.py    TaskMemory — evidence cache + intermediate results (extends Module-1 memory)
    research_agent.py Research Agent (plan → search → rank → gaps → report)
    writing_agent.py  Writing Agent (many doc types; reuses evidence + AnswerService)
    comparison_agent.py Comparison Agent (per-target evidence → similarities/differences/conflicts)
    study_agent.py    Study Agent (reuses Summary/Notes/Flashcards + Knowledge Dashboard + study plan)
    workflows.py      Serializable WorkflowDefinition + WorkflowEngine (research→write, study pack, …)
    registry.py       task_type → agent implementation
"""
