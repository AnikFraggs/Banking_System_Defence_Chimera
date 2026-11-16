# Credit brain: shipped JSON LR vs ONNX Runtime serving (SYNTHETIC data)

Splits reproduced and verified against `credit-brain-lr-v2`: {'train': 28067, 'val': 8985, 'test': 8028, 'adaptive_holdout': 4920}.
ONNX LR parity: max |dp| test 2.86e-07, holdout 3.26e-07; decision agreement 1.0.

| Model | test ROC | test PR | holdout ROC | holdout PR | holdout recall(any) | holdout FPR(any) | holdout recall(review) | p50 ms | p99 ms |
|---|---|---|---|---|---|---|---|---|---|
| json_lr_shipped | 0.9733 | 0.9576 | 0.9535 | 0.9189 | 0.896 | 0.0169 | 0.8523 | 0.0073 | 0.0084 |
| onnx_lr | 0.9733 | 0.9576 | 0.9535 | 0.9189 | 0.896 | 0.0169 | 0.8523 | 0.0102 | 0.0112 |
| onnx_mlp_64x32 | 0.9796 | 0.9601 | 0.9604 | 0.931 | 0.9295 | 0.0307 | 0.9161 | 0.011 | 0.0119 |
| hgb_python | 0.9774 | 0.96 | 0.963 | 0.9354 | 0.9329 | 0.0547 | 0.9161 | 0.2951 | 0.4882 |
| lightgbm_python | 0.976 | 0.9575 | 0.9596 | 0.9369 | 0.9262 | 0.0151 | 0.9262 | 0.2035 | 0.3485 |
