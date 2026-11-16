"""Strict loading and inference for the creditcard HistGradientBoosting artifact."""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier


class ModelUnavailable(RuntimeError):
    """The model cannot provide a trustworthy score."""


class InvalidFeatures(ValueError):
    """The supplied named feature vector does not match the artifact."""


class CardModel:
    """An immutable, already-loaded binary card model.

    Tests can construct this class directly around a deterministic fake estimator.
    Production instances must come through :meth:`load`, which requires a real
    HistGradientBoostingClassifier.
    """

    def __init__(
        self,
        model: Any,
        features: Sequence[str],
        version: str,
        threshold: float,
    ) -> None:
        self.model = model
        self.features = tuple(features)
        self.version = version
        self.threshold = float(threshold)
        # Concurrent single-row predicts convoy on the GIL around sklearn's nogil sections:
        # 10-way p50 rose from 0.8 ms to 65 ms in-container. Serialising keeps every call ~1 ms.
        self._predict_lock = threading.Lock()

    @classmethod
    def load(cls, path: str | Path) -> "CardModel":
        artifact_path = Path(path)
        if artifact_path.suffix.lower() == ".onnx":
            from .onnx_card_model import OnnxCardModel

            return OnnxCardModel.load(artifact_path)  # type: ignore[return-value]
        if not artifact_path.is_file():
            raise ModelUnavailable(f"model artifact not found: {artifact_path}")
        try:
            artifact = joblib.load(artifact_path)
        except Exception as exc:
            raise ModelUnavailable("model artifact could not be loaded") from exc

        if not isinstance(artifact, dict):
            raise ModelUnavailable("model artifact must be a metadata dictionary")
        model = artifact.get("model")
        features = artifact.get("features")
        version = artifact.get("version")
        threshold = artifact.get("threshold")

        if not isinstance(model, HistGradientBoostingClassifier):
            raise ModelUnavailable("artifact estimator must be HistGradientBoostingClassifier")
        if (
            not isinstance(features, (list, tuple))
            or not features
            or any(not isinstance(name, str) or not name for name in features)
            or len(set(features)) != len(features)
        ):
            raise ModelUnavailable("artifact features must be unique, non-empty names")
        if not isinstance(version, str) or not version.strip():
            raise ModelUnavailable("artifact version must be a non-empty string")
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or not 0 <= float(threshold) <= 1
        ):
            raise ModelUnavailable("artifact threshold must be in [0, 1]")
        if getattr(model, "n_features_in_", None) != len(features):
            raise ModelUnavailable("artifact feature count does not match the estimator")
        if not hasattr(model, "predict_proba"):
            raise ModelUnavailable("artifact estimator has no probability output")

        return cls(model, features, version.strip(), float(threshold))

    def ordered_vector(self, card_features: Mapping[str, Any] | None) -> list[float]:
        if card_features is None:
            raise InvalidFeatures("card_features is required by the loaded model")
        supplied = set(card_features)
        expected = set(self.features)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise InvalidFeatures(f"feature mismatch; missing={missing}, extra={extra}")

        vector: list[float] = []
        for name in self.features:  # artifact order is the only inference order
            value = card_features[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidFeatures(f"feature {name!r} must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise InvalidFeatures(f"feature {name!r} must be finite")
            vector.append(number)
        return vector

    def score(self, card_features: Mapping[str, Any] | None) -> float:
        vector = self.ordered_vector(card_features)
        try:
            matrix = np.asarray([vector], dtype=np.float64)
            with self._predict_lock:
                probabilities = np.asarray(self.model.predict_proba(matrix))
            classes = list(getattr(self.model, "classes_", []))
            fraud_index = classes.index(1)
            if probabilities.shape != (1, len(classes)):
                raise ValueError("unexpected probability shape")
            score = float(probabilities[0, fraud_index])
        except InvalidFeatures:
            raise
        except Exception as exc:
            raise ModelUnavailable("card model scoring failed") from exc
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ModelUnavailable("card model returned an invalid probability")
        return score
