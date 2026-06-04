# Phase 2 — Context Engineering Evaluation (Before vs After)

- Queries: **10**
- Total context tokens — before: **20547**, after: **18686** (**9.1%** reduction)

| Metric | Value |
|--------|-------|
| Mean compression ratio | 0.063 |
| Mean duplicate reduction rate | 0.100 |
| Mean citation coverage | 1.000 |
| Mean context relevance | 0.606 |
| Mean context density | 0.319 |

## Per-query

| Query | Before→After tokens | Compr. | Dup↓ | Cite cov. | Relevance | Density |
|-------|---------------------|--------|------|-----------|-----------|---------|
| How does the operating system schedule pro… | 2553→2377 | 0.07 | 0.20 | 1.00 | 0.88 | 0.31 |
| What is a deadlock and how can it be preve… | 3126→3160 | -0.01 | 0.00 | 1.00 | 0.50 | 0.22 |
| Explain virtual memory and paging. | 2525→2558 | -0.01 | 0.00 | 1.00 | 0.70 | 0.37 |
| What is mutual exclusion in concurrent pro… | 2343→1801 | 0.23 | 0.20 | 1.00 | 0.69 | 0.20 |
| How do semaphores work for synchronization? | 1959→1666 | 0.15 | 0.20 | 1.00 | 0.42 | 0.29 |
| What is the difference between a process a… | 1744→1560 | 0.10 | 0.20 | 1.00 | 0.69 | 0.33 |
| How does demand paging reduce memory usage? | 3415→2611 | 0.24 | 0.20 | 1.00 | 0.65 | 0.28 |
| What are the prerequisites for learning AI? | 278→296 | -0.06 | 0.00 | 1.00 | 0.67 | 0.67 |
| What is the recommended roadmap to master … | 351→369 | -0.05 | 0.00 | 1.00 | 0.60 | 0.30 |
| How do Java generics and the collections f… | 2253→2288 | -0.02 | 0.00 | 1.00 | 0.28 | 0.24 |
