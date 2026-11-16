# Credit brain v2 (LR) vs v3 candidate (LightGBM, stdlib trees) - SYNTHETIC

stdlib-vs-lightgbm parity max |dp| 0.00e+00; 300 trees; model 665786 bytes.

| model | set | PR-AUC | recall(any) | FPR(any) | recall(review) | FPR(review) |
|---|---|---|---|---|---|---|
| v2_lr | test | 0.9576 | 0.9524 | 0.0199 | 0.9524 | 0.0133 |
| v2_lr | adaptive_holdout | 0.9189 | 0.896 | 0.0169 | 0.8523 | 0.0121 |
| v2_lr | stress_fresh_rings | 0.9318 | 0.9024 | 0.0191 | 0.877 | 0.012 |
| v2_lr | stress_stealth_graft | 0.9262 | 0.8944 | 0.0191 | 0.861 | 0.012 |
| v3_lgbm | test | 0.9575 | 0.9524 | 0.0184 | 0.9524 | 0.0159 |
| v3_lgbm | adaptive_holdout | 0.9369 | 0.9262 | 0.0151 | 0.9262 | 0.0123 |
| v3_lgbm | stress_fresh_rings | 0.9421 | 0.9305 | 0.0165 | 0.9291 | 0.0142 |
| v3_lgbm | stress_stealth_graft | 0.942 | 0.9305 | 0.0165 | 0.9291 | 0.0142 |

| model | assess p50 ms | p95 | p99 |
|---|---|---|---|
| v2_lr | 0.0107 | 0.0132 | 0.0164 |
| v3_lgbm | 0.2047 | 0.259 | 0.3949 |
