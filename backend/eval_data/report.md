# Phase 1 Retrieval — Before/After Comparison

| Config | Recall@5 | Precision@5 | MRR | Mean latency (ms) |
|--------|----------|-------------|-----|-------------------|
| Baseline (dense-only) | 1.000 | 1.000 | 1.000 | 72.1 |
| Hybrid (dense+BM25+RRF) | 1.000 | 0.800 | 0.950 | 20.9 |
| Full (hybrid+rerank) | 1.000 | 0.820 | 0.950 | 1563.6 |

---

# Baseline — Dense-only (pre-Phase-1)

- Queries evaluated: **10**

| K | Recall@K | Precision@K |
|---|----------|-------------|
| 1 | 1.0000 | 1.0000 |
| 3 | 1.0000 | 1.0000 |
| 5 | 1.0000 | 1.0000 |
| 10 | 1.0000 | 0.9800 |

- **MRR**: 1.0000

## Latency

- mean: 72.1 ms
- p50: 14.3 ms
- p95: 591.5 ms

---

# Hybrid — Dense + BM25 + RRF

- Queries evaluated: **10**

| K | Recall@K | Precision@K |
|---|----------|-------------|
| 1 | 0.9000 | 0.9000 |
| 3 | 1.0000 | 0.8000 |
| 5 | 1.0000 | 0.8000 |
| 10 | 1.0000 | 0.7800 |

- **MRR**: 0.9500

## Latency

- mean: 20.9 ms
- p50: 21.2 ms
- p95: 22.5 ms

---

# Full Pipeline — Hybrid + BGE Reranker

- Queries evaluated: **10**

| K | Recall@K | Precision@K |
|---|----------|-------------|
| 1 | 0.9000 | 0.9000 |
| 3 | 1.0000 | 0.8333 |
| 5 | 1.0000 | 0.8200 |
| 10 | 1.0000 | 0.8000 |

- **MRR**: 0.9500

## Latency

- mean: 1563.6 ms
- p50: 966.6 ms
- p95: 8313.9 ms
