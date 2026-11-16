# Wire gate benchmark — PaySim (synthetic, temporal split)

Rows train/val/test: 4453834/954393/954393; test fraud 0.4200%; FPR budget 0.01 (validation-only threshold).

| Model | ROC-AUC | PR-AUC | Recall@FPR | Precision | FPR | subset PR | p50 ms |
|---|---|---|---|---|---|---|---|
| hgb_production | 1.0 | 1.0 | 0.9968 | 1.0000 | 0.00000 | 1.0 | 1.9077 |
| xgboost | 1.0 | 0.99995 | 0.9970 | 1.0000 | 0.00000 | 0.99995 | 0.6545 |
| lightgbm | 1.0 | 0.99999 | 0.9965 | 1.0000 | 0.00000 | 0.99999 | 0.4289 |
