# Credit brain benchmark — SYNTHETIC credit-boost data (not real-world quality)

Rows train/val/test/adaptive: 24028/7944/8028/10000; test positives 651, adaptive positives 741.

| Model | test ROC | test PR | adaptive ROC | adaptive PR | p50 ms |
|---|---|---|---|---|---|
| lr_shipped | 0.9756 | 0.9595 | 0.9579 | 0.886 | 0.0668 |
| hgb | 0.9754 | 0.9583 | 0.94 | 0.8782 | 0.6324 |
| xgboost | 0.9744 | 0.9585 | 0.9596 | 0.8976 | 0.456 |
| lightgbm | 0.9748 | 0.9574 | 0.9666 | 0.9289 | 0.4345 |
