"""Run the retrieval evaluation and emit a before/after comparison report.

Compares three retrieval configurations on the same ground-truth set:
  - baseline : dense-only top-K (the pre-Phase-1 pipeline: embed -> FAISS -> top-K)
  - hybrid   : dense + BM25 fused with RRF (no rerank)
  - pipeline : full Phase-1 pipeline (hybrid -> BGE cross-encoder rerank)

Usage (from backend/):
    python -m scripts.run_eval                         # baseline + hybrid
    LEXIMIND_ENABLE_RERANKER=1 python -m scripts.run_eval --rerank   # all three
    python -m scripts.run_eval --dataset eval_data/sample_ground_truth.json --out report.md
"""

from __future__ import annotations

import argparse

from app.core.config import settings
from app.core.state import bm25_retriever, dense_retriever, hybrid_retriever, pipeline
from app.eval.framework import RetrievalEvaluator, load_dataset
from app.retrieval.reranker import RerankerService
from app.services.embedding_service import generate_embedding

K_VALUES = [1, 3, 5, 10]
FINAL_K = max(K_VALUES)


def _baseline_fn(query: str):
    # Reproduces the old retrieval path exactly: embed the query, FAISS top-K.
    return dense_retriever.retrieve(generate_embedding(query), FINAL_K)


def _hybrid_fn(query: str):
    return hybrid_retriever.retrieve(
        query=query,
        query_embedding=generate_embedding(query),
        dense_top_k=settings.dense_top_k,
        sparse_top_k=settings.sparse_top_k,
        top_k=FINAL_K,
    )


def _pipeline_fn(reranker: RerankerService):
    def fn(query: str):
        result = pipeline.run(query, embed_fn=generate_embedding, final_top_k=FINAL_K)
        return result.chunks
    # Ensure reranking is active for this run regardless of env flag.
    pipeline.reranker = reranker
    pipeline.enable_reranker = True
    return fn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval_data/sample_ground_truth.json")
    parser.add_argument("--out", default="eval_data/report.md")
    parser.add_argument("--rerank", action="store_true", help="also evaluate the full pipeline with BGE reranking")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    ev = RetrievalEvaluator(dataset, k_values=K_VALUES)

    # Warm the BM25 index once so its build cost isn't charged to the first query.
    bm25_retriever.build()

    sections = []
    print("Evaluating BASELINE (dense-only)...")
    baseline = ev.evaluate(_baseline_fn)
    sections.append(baseline.to_markdown("Baseline — Dense-only (pre-Phase-1)"))

    print("Evaluating HYBRID (dense + BM25 + RRF)...")
    hybrid = ev.evaluate(_hybrid_fn)
    sections.append(hybrid.to_markdown("Hybrid — Dense + BM25 + RRF"))

    full = None
    if args.rerank:
        print("Evaluating FULL PIPELINE (hybrid + BGE rerank)...")
        full = ev.evaluate(_pipeline_fn(RerankerService(settings.reranker_model)))
        sections.append(full.to_markdown("Full Pipeline — Hybrid + BGE Reranker"))

    # Compact comparison table.
    comp = ["# Phase 1 Retrieval — Before/After Comparison", "",
            "| Config | Recall@5 | Precision@5 | MRR | Mean latency (ms) |",
            "|--------|----------|-------------|-----|-------------------|"]
    rows = [("Baseline (dense-only)", baseline), ("Hybrid (dense+BM25+RRF)", hybrid)]
    if full is not None:
        rows.append(("Full (hybrid+rerank)", full))
    for name, rep in rows:
        comp.append(
            f"| {name} | {rep.recall_at_k[5]:.3f} | {rep.precision_at_k[5]:.3f} "
            f"| {rep.mrr:.3f} | {rep.latency_ms['mean']:.1f} |"
        )

    report = "\n".join(comp) + "\n\n---\n\n" + "\n\n---\n\n".join(sections) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + "\n".join(comp))
    print(f"\nFull report written to {args.out}")


if __name__ == "__main__":
    main()
