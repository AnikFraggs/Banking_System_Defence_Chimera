from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from training.train_creditcard_hgb import (
    FEATURES,
    classification_metrics,
    load_local_csv,
    temporal_split,
    threshold_at_fpr,
)


def test_temporal_split_preserves_time_order_and_partitions():
    frame = pd.DataFrame({
        "Time": np.arange(100),
        "Class": np.asarray([0, 1] * 50),
        **{name: np.zeros(100) for name in FEATURES},
    })
    train, validation, test = temporal_split(frame)
    assert (len(train), len(validation), len(test)) == (70, 15, 15)
    assert train["Time"].max() < validation["Time"].min()
    assert validation["Time"].max() < test["Time"].min()


def test_validation_threshold_respects_zero_fpr_budget():
    labels = np.asarray([0, 0, 0, 1, 1])
    scores = np.asarray([0.1, 0.2, 0.8, 0.7, 0.9])
    threshold = threshold_at_fpr(labels, scores, max_fpr=0.0)
    assert threshold == 0.9
    metrics = classification_metrics(labels, scores, threshold)
    assert metrics["recall"] == 0.5
    assert metrics["precision"] == 1.0
    assert metrics["fpr"] == 0.0


def test_training_data_is_explicitly_required(tmp_path):
    with pytest.raises(FileNotFoundError, match="no dataset is downloaded or bundled"):
        load_local_csv(tmp_path / "absent-creditcard.csv")
