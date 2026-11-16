# L4 semantic guard benchmark — locked v5 held-out slices

Common max_length=128; threshold = worst-case FPR<= 0.02 across both calib slices; never selected on test. external_test is the honest generalization slice (SPML).

| Model | Deployable<100M | Thr | ext recall [CI95] | ext FPR [CI95] | ext prec | in-dom recall | in-dom FPR | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| chimera_l4_v5 (mine) | True | 0.915675 | 0.1621 [0.155, 0.1694] | 0.022 [0.0171, 0.0283] | 0.9651 | 0.7907 | 0.004 | 6.118 | 8.531 |
| chimera_l4_v4 (mine, prev) | True | 0.99409 | 0.2144 [0.2065, 0.2225] | 0.0149 [0.011, 0.0203] | 0.9818 | 0.7636 | 0.0 | 5.085 | 8.678 |
| chimera_l4_v1 (deployed toy) | True | 0.535529 | 0.0607 [0.0562, 0.0655] | 0.0 [0.0, 0.0014] | 1.0 | 0.0078 | 0.021 | 1.594 | 2.886 |
| protectai_deberta_v3 (rival) | False | 0.999943 | 0.8831 [0.8766, 0.8892] | 0.0108 [0.0076, 0.0155] | 0.9967 | 0.6357 | 0.0 | 174.358 | 258.455 |
| tfidf_logreg (baseline) | True | 0.480954 | 0.3502 [0.341, 0.3596] | 0.0273 [0.0217, 0.0341] | 0.9797 | 0.8953 | 0.012 | 0.407 | 1.112 |

**Correction (2026-11-14):** the v1 row above is INVALID (harness fallback tokenizer had a 5-token vocab under transformers 5). Re-measured with the fixed harness (`build-check/l4_distill/bench_v1_fixed/`): thr 0.732812, ext recall 0.0019 [0.0012, 0.0029], ext FPR 0.0, in-dom recall 0.0853, in-dom FPR 0.022, p50 0.772 / p95 1.493 ms. Distilled v6 results: `build-check/l4_distill/bench_v6/` and MODEL_BENCHMARKS.md section 3.1.
