"""Phase-2 context-engineering evaluation: before vs after.

For each query in a dataset, runs Phase-1 retrieval, then compares:
  - BEFORE: naive context = raw concatenation of the retrieved chunk texts (the pre-Phase-2
            behavior), and its token count.
  - AFTER : the engineered context from ContextBuilderService, plus its quality metrics.

Aggregates and writes a markdown report:
  token usage, token efficiency, compression ratio, duplicate reduction rate,
  citation preservation rate, context relevance & density.

Usage (from backend/):
    python -m scripts.run_context_eval
    python -m scripts.run_context_eval --dataset eval_data/sample_ground_truth.json --out eval_data/context_report.md
"""

from __future__ import annotations

import argparse
from statistics import mean

from app.core.state import context_builder, pipeline
from app.eval.framework import load_dataset
from app.services.embedding_service import generate_embedding


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval_data/sample_ground_truth.json")
    parser.add_argument("--out", default="eval_data/context_report.md")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    counter = context_builder.counter

    rows = []
    for item in dataset:
        result = pipeline.run(item.query, embed_fn=generate_embedding)
        before_text = "\n\n".join(c.text for c in result.chunks)
        before_tokens = counter.count(before_text)

        ctx = context_builder.build(item.query, result.chunks, query_keywords=result.analysis.keywords)
        m = ctx.metrics
        rows.append({
            "query": item.query,
            "before_tokens": before_tokens,
            "after_tokens": m["final_tokens"],
            "compression_ratio": m["compression_ratio"],
            "dup_reduction": m["duplicate_reduction_rate"],
            "citation_coverage": m["citation_coverage"],
            "relevance": m["context_relevance"],
            "density": m["context_density"],
            "chunks_in": m["num_input_chunks"],
            "chunks_used": m["num_chunks_used"],
        })

    def avg(key):
        return mean(r[key] for r in rows) if rows else 0.0

    total_before = sum(r["before_tokens"] for r in rows)
    total_after = sum(r["after_tokens"] for r in rows)
    token_saving = (1 - total_after / total_before) if total_before else 0.0

    lines = [
        "# Phase 2 — Context Engineering Evaluation (Before vs After)", "",
        f"- Queries: **{len(rows)}**",
        f"- Total context tokens — before: **{total_before}**, after: **{total_after}** "
        f"(**{token_saving*100:.1f}%** reduction)", "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Mean compression ratio | {avg('compression_ratio'):.3f} |",
        f"| Mean duplicate reduction rate | {avg('dup_reduction'):.3f} |",
        f"| Mean citation coverage | {avg('citation_coverage'):.3f} |",
        f"| Mean context relevance | {avg('relevance'):.3f} |",
        f"| Mean context density | {avg('density'):.3f} |",
        "",
        "## Per-query", "",
        "| Query | Before→After tokens | Compr. | Dup↓ | Cite cov. | Relevance | Density |",
        "|-------|---------------------|--------|------|-----------|-----------|---------|",
    ]
    for r in rows:
        q = (r["query"][:42] + "…") if len(r["query"]) > 43 else r["query"]
        lines.append(
            f"| {q} | {r['before_tokens']}→{r['after_tokens']} | {r['compression_ratio']:.2f} "
            f"| {r['dup_reduction']:.2f} | {r['citation_coverage']:.2f} | {r['relevance']:.2f} | {r['density']:.2f} |"
        )

    report = "\n".join(lines) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n".join(lines[:12]))
    print(f"\nFull report written to {args.out}")


if __name__ == "__main__":
    main()
