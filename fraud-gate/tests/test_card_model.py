from __future__ import annotations

import joblib
import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from app.card_model import CardModel, InvalidFeatures, ModelUnavailable


def test_real_hgb_joblib_round_trip_and_strict_features(tmp_path):
    x = np.asarray([[0.0, 0.0], [0.1, 0.2], [0.8, 0.7], [1.0, 1.0]] * 5)
    y = np.asarray([0, 0, 1, 1] * 5)
    estimator = HistGradientBoostingClassifier(max_iter=5, min_samples_leaf=2, random_state=7)
    estimator.fit(x, y)
    path = tmp_path / "synthetic_hgb.joblib"
    joblib.dump(
        {"model": estimator, "features": ["V1", "V2"], "version": "hgb-test", "threshold": 0.4},
        path,
    )

    loaded = CardModel.load(path)
    score = loaded.score({"V2": 0.7, "V1": 0.8})
    assert 0 <= score <= 1
    assert loaded.version == "hgb-test"
    with pytest.raises(InvalidFeatures):
        loaded.score({"V1": 0.8})


def test_loader_rejects_missing_artifact_and_wrong_estimator(tmp_path):
    with pytest.raises(ModelUnavailable):
        CardModel.load(tmp_path / "absent.joblib")

    wrong_path = tmp_path / "wrong.joblib"
    estimator = LogisticRegression().fit([[0.0], [1.0]], [0, 1])
    joblib.dump(
        {"model": estimator, "features": ["V1"], "version": "wrong", "threshold": 0.5},
        wrong_path,
    )
    with pytest.raises(ModelUnavailable):
        CardModel.load(wrong_path)
