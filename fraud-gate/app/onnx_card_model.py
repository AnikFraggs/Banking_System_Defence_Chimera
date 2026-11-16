"""Strict ONNX Runtime card scoring backend with a sidecar metadata contract."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .card_model import InvalidFeatures, ModelUnavailable


class OnnxCardModel:
    """Optional optimized card inference; identical feature contract to joblib."""

    def __init__(
        self,
        session: Any,
        input_name: str,
        output_name: str,
        features: Sequence[str],
        version: str,
        threshold: float,
    ) -> None:
        self.session = session
        self.input_name = input_name
        self.output_name = output_name
        self.features = tuple(features)
        self.version = version
        self.threshold = float(threshold)

    @classmethod
    def load(cls, path: str | Path, metadata_path: str | Path | None = None) -> "OnnxCardModel":
        from onnxruntime import InferenceSession

        model_path = Path(path)
        if not model_path.is_file():
            raise ModelUnavailable(f"ONNX model not found: {model_path}")
        sidecar = Path(metadata_path) if metadata_path else model_path.with_suffix(".json")
        if not sidecar.is_file():
            raise ModelUnavailable(f"ONNX metadata sidecar not found: {sidecar}")
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ModelUnavailable("ONNX metadata is not valid JSON") from exc
        if not isinstance(metadata, dict):
            raise ModelUnavailable("ONNX metadata must be an object")
        features = metadata.get("features")
        version = metadata.get("version")
        threshold = metadata.get("threshold")
        if (
            not isinstance(features, (list, tuple))
            or not features
            or any(not isinstance(name, str) or not name for name in features)
            or len(set(features)) != len(features)
        ):
            raise ModelUnavailable("ONNX metadata features must be unique names")
        if not isinstance(version, str) or not version.strip():
            raise ModelUnavailable("ONNX metadata version must be a non-empty string")
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or not 0 <= float(threshold) <= 1
        ):
            raise ModelUnavailable("ONNX metadata threshold must be in [0, 1]")
        try:
            session = InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise ModelUnavailable("ONNX session could not be created") from exc
        inputs = [item.name for item in session.get_inputs()]
        outputs = [item.name for item in session.get_outputs()]
        if not inputs or not outputs:
            raise ModelUnavailable("ONNX model has no inputs or outputs")
        return cls(
            session, inputs[0], outputs[0], tuple(features), version.strip(), float(threshold)
        )

    def score(self, card_features: Mapping[str, Any] | None) -> float:
        if card_features is None:
            raise InvalidFeatures("card_features is required by the loaded model")
        supplied = set(card_features)
        expected = set(self.features)
        if supplied != expected:
            raise InvalidFeatures(
                f"feature mismatch; missing={sorted(expected - supplied)}, extra={sorted(supplied - expected)}"
            )
        vector: list[float] = []
        for name in self.features:
            value = card_features[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidFeatures(f"feature {name!r} must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise InvalidFeatures(f"feature {name!r} must be finite")
            vector.append(number)
        try:
            matrix = np.asarray([vector], dtype=np.float32)
            outputs = self.session.run(
                [self.output_name], {self.input_name: matrix}
            )
            probabilities = np.asarray(outputs[0], dtype=np.float64)
        except Exception as exc:
            raise ModelUnavailable("ONNX card scoring failed") from exc
        if probabilities.shape[0] != 1 or probabilities.shape[1] != 2:
            raise ModelUnavailable("ONNX output must be a [1, 2] probability tensor")
        score = float(probabilities[0, 1])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ModelUnavailable("ONNX returned an invalid probability")
        return score
