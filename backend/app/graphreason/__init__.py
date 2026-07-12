"""Graph Reasoning & Explainable AI (Phase 7, Module 3) — the graph becomes a reasoning engine.

Where Module 2 RETRIEVES a neighborhood, this module REASONS: multi-hop reasoning paths, implicit
relationship inference (transitive rules), confidence propagation (evidence → edges → paths →
conclusion), dependency + root-cause analysis, graph-assisted verification (REUSING the Phase-6
Verification Engine), and STRUCTURED explainable reasoning metadata (never chain-of-thought). It reuses
Module-1 graph + Module-2 recognition + Phase-6 verification — no new retrieval/inference pipeline — and
feeds a reasoning-context block into the single PromptPackage → AnswerService pathway via `graph_reason`.

    interfaces.py    ReasoningPath / ReasonedRelationship / DependencyChain / ReasoningResult + Protocols
    paths.py         PathReasoner (multi-hop DFS paths, weighted, cycle-protected) + build_adjacency
    inference.py     RelationshipInference (transitive composition rules; inferred edges kept separate)
    confidence.py    ConfidencePropagation (node/edge/path/overall; reuses Phase-6 ConfidenceBreakdown)
    dependency.py    DependencyAnalyzer + RootCause (directed dependency chains)
    verification.py  GraphVerificationAdapter (reuses GraphValidator + VerificationService)
    explanation.py   ExplanationBuilder (structured reasoning metadata; no chain-of-thought)
    context.py       reasoning-aware context assembly for the PromptPackage
    cache.py         ReasoningCache (avoid repeated reasoning over identical subgraphs)
    engine.py        GraphReasoner (orchestrator)
    models/repository/service/schemas/api  GraphReasoningLog + inferred-edge persistence + DTOs + routes
"""
