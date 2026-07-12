"""Verification & Reasoning Engine (Phase 6, Module 3) — LexiMind's trust layer.

Turns "retrieve + generate" into "reason + verify": after the SINGLE AnswerService produces a draft,
this engine validates every important claim against the retrieved evidence, detects contradictions
across sources/modalities, estimates confidence from MEASURABLE system signals (not LLM self-report),
validates citations, self-reviews the draft, and emits a structured, explainable VerificationReport.

It creates NO retrieval/context/LLM pipeline — it consumes the evidence Phases 1/2/4/5 already
produced and, only in `thorough` mode, makes ONE optional critique through the same `answer_fn`.

    textutil.py             deterministic NLP primitives (overlap/negation/numbers)
    interfaces.py           Protocols + value objects (Claim/ClaimVerdict/Contradiction/Confidence/Report)
    claims.py               claim extraction from a draft answer
    evidence_validator.py   supported / weak / unsupported / conflicting per claim
    contradiction.py        claim↔evidence + evidence↔evidence conflict detection
    confidence.py           weighted measurable-signal confidence
    citation_validator.py   broken / missing / weak / duplicate citation checks
    self_review.py          bounded deterministic (+ optional single-LLM) review + recommendations
    explanation.py          structured reasoning metadata (no chain-of-thought)
    engine.py               ReasoningEngine — orchestrates the pipeline (+ content cache)
    models/repository/service/schemas/api  VerificationLog + coordination + DTOs + routes
"""
