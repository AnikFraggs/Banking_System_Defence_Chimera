# Card fraud benchmark — ULB creditcard.csv (real, temporal split)

Rows train/val/test: 199364/42721/42722; test fraud rate 0.1217%; FPR budget 0.01 (threshold chosen on validation only).

| Model | ROC-AUC | PR-AUC | Recall@FPR | Precision | FPR | Brier | train s | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| hgb_production | 0.95705 | 0.75065 | 0.82692 | 0.11653 | 0.00764 | 0.000538 | 10.32 | 0.762 | 0.8677 |
| xgboost | 0.97932 | 0.76746 | 0.76923 | 0.24845 | 0.002836 | 0.000474 | 1.79 | 0.1858 | 0.2143 |
| lightgbm | 0.87252 | 0.65773 | 0.76923 | 0.11111 | 0.007499 | 0.000668 | 0.94 | 0.1846 | 0.204 |
