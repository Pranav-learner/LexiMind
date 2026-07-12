"""Continuous Learning & Feedback Platform (Phase 8, Module 4) — LexiMind's improvement engine.

Closes the loop: Response → Feedback → Learning Engine → Analysis → Recommendations → Human Review →
(future) Improvement. It CONSUMES signals from every subsystem (feedback + VerificationLog + AgentTaskLog +
OptimizationRunLog) and PRODUCES explainable, GOVERNED recommendations for prompts / retrieval / agents /
datasets — it never auto-modifies production behavior (all changes pass through the human review queue).

    interfaces.py      FailureSignal / FailureCluster / LearningRec + LearningSource protocol
    models.py          Feedback / LearningRecommendation (review queue + audit) / LearningCycleLog
    feedback.py        FeedbackManager — unified feedback (thumbs/star/text/correction/citation/…), anon+auth
    analyzer.py        ErrorAnalyzer — collect failure signals from logs + feedback, categorize, cluster
    learners.py        Prompt / Retrieval / Agent learning engines (recommend, never modify)
    dataset_builder.py DatasetBuilder — failures → EvalDataset/EvalItem (reuses Evaluation Framework)
    review.py          HumanReviewQueue — approve/reject with audit (governance; never auto-applies)
    engine.py          LearningEngine — one learning cycle (analyze → recommend → persist pending → log)
    repository/service/schemas/api/errors  data access + orchestration + DTOs + routes
"""
