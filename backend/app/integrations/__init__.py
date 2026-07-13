"""Phase 9 · Module 3 — External Integrations & Automation Platform.

Transforms LexiMind from an isolated AI platform into an enterprise AI Integration Hub.

Architecture:

    External Systems  →  Connector SDK  →  Integration Runtime
                                          ↓
                                     Event Bus  →  Automation Engine
                                          ↓              ↓
                                     Webhook Mgr    Agent Runtime (reused)
                                          ↓              ↓
                                     Scheduler     Knowledge Graph (reused)
                                          ↓              ↓
                                     MCP Client    AnswerService (reused)

Key design principles:
- Interface-driven: BaseConnector protocol; future connectors plug in without core changes.
- Reuse everything: Agent Runtime, Orchestrator, Security, Observability, Crypto — no duplication.
- Offline-first: In-process scheduling, no Celery/Redis/RabbitMQ dependencies.
- Zero Trust: All connector credentials encrypted via existing Fernet crypto.
"""
