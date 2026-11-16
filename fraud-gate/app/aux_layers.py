"""Optional, fail-closed auxiliary scoring layers served by the fraud gate.

Three research models are exposed as independent REST layers, each loaded once at
startup and never in the request path:

* account-opening fraud (Feedzai BAF, XGBoost)
* transaction AML laundering (IBM AMLworld HI-Small, HistGradientBoosting)
* web-attack text (SQLi/XSS/command injection, TF-IDF + logistic)

Every layer is escalate-only: a score at or above its calibration-derived
threshold yields CHALLENGE, otherwise PASS. Missing artifacts or invalid features
fail closed to CHALLENGE (never silently PASS). These layers do not alter the
existing pre-capture checkout fusion; they are additive defence surfaces.

All datasets are synthetic; these are research models, not production-readiness
claims. See fraud-gate/training/artifacts/*/metadata.json for measured holdouts.
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
from prometheus_client import Counter, Gauge, Histogram

AUX_SCORES_TOTAL = Counter(
    "chimera_aux_layer_scores_total",
    "Auxiliary layer decisions, labelled by layer, decision and fallback flag.",
    ["layer", "decision", "fallback"],
)
AUX_LATENCY_MS = Histogram(
    "chimera_aux_layer_latency_ms",
    "Auxiliary layer scoring latency in milliseconds.",
    ["layer"],
    buckets=(1, 2, 5, 10, 25, 50, 100, 250, 500, 1000),
)
AUX_MODEL_LOADED = Gauge(
    "chimera_aux_layer_model_loaded",
    "1 when an auxiliary model is loaded; 0 when failing closed to CHALLENGE.",
    ["layer"],
)
AUX_SCORE = Histogram(
    "chimera_aux_layer_score",
    "Auxiliary layer risk score.",
    ["layer"],
    buckets=(0, .1, .25, .35, .5, .75, .85, .95, 1),
)
for _layer in ("account_opening", "aml", "web_attack"):
    AUX_MODEL_LOADED.labels(layer=_layer)
    for _decision in ("PASS", "CHALLENGE"):
        for _fallback in ("true", "false"):
            AUX_SCORES_TOTAL.labels(layer=_layer, decision=_decision, fallback=_fallback)


class ModelUnavailable(RuntimeError):
    """The auxiliary model cannot provide a trustworthy score."""


class InvalidFeatures(ValueError):
    """The supplied features do not match the artifact contract."""


def _load_metadata(directory: Path) -> dict:
    meta_path = directory / "metadata.json"
    if not meta_path.is_file():
        raise ModelUnavailable(f"metadata.json not found in {directory}")
    try:
        return json.loads(meta_path.read_text())
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable("metadata.json could not be parsed") from exc


def _threshold(meta: dict, path: list[str]) -> float:
    node: Any = meta
    for key in path:
        node = node[key]
    value = float(node)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ModelUnavailable("calibration threshold must be in [0,1]")
    return value


class AccountOpeningModel:
    SENTINEL = ("prev_address_months_count", "current_address_months_count", "credit_risk_score",
                "bank_months_count", "session_length_in_minutes", "device_distinct_emails_8w")

    def __init__(self, model: Any, preprocessor: Any, numeric: list[str],
                 categorical: list[str], version: str, threshold: float) -> None:
        self.model = model
        self.preprocessor = preprocessor
        self.numeric = tuple(numeric)
        self.categorical = tuple(categorical)
        self.version = version
        self.threshold = threshold
        self._lock = threading.Lock()

    @classmethod
    def load(cls, directory: str | Path) -> "AccountOpeningModel":
        directory = Path(directory)
        meta = _load_metadata(directory)
        artifact_path = directory / "model.joblib"
        if not artifact_path.is_file():
            raise ModelUnavailable(f"model.joblib not found in {directory}")
        try:
            bundle = joblib.load(artifact_path)
            model = bundle["model"]
            preprocessor = bundle["preprocessor"]
            if not hasattr(model, "predict_proba"):
                raise ModelUnavailable("account-opening estimator has no probability output")
            numeric = list(meta["features"]["numeric"])
            categorical = list(meta["features"]["categorical"])
            version = str(meta["version"])
            threshold = _threshold(meta, ["results", meta["selected_model"], "calibration", "threshold"])
        except ModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable("account-opening artifact could not be loaded") from exc
        return cls(model, preprocessor, numeric, categorical, version, threshold)

    def score(self, features: Mapping[str, Any] | None) -> float:
        if features is None:
            raise InvalidFeatures("features are required")
        expected = set(self.numeric) | set(self.categorical)
        supplied = set(features)
        if supplied != expected:
            raise InvalidFeatures(
                f"feature mismatch; missing={sorted(expected - supplied)}, extra={sorted(supplied - expected)}")
        row: dict[str, Any] = {}
        for name in self.numeric:
            value = features[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidFeatures(f"feature {name!r} must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise InvalidFeatures(f"feature {name!r} must be finite")
            row[name] = np.nan if (name in self.SENTINEL and number == -1) else number
        for name in self.categorical:
            value = features[name]
            if not isinstance(value, str) or not value:
                raise InvalidFeatures(f"feature {name!r} must be a non-empty string")
            row[name] = value
        frame = pd.DataFrame([row], columns=list(self.numeric) + list(self.categorical))
        try:
            matrix = self.preprocessor.transform(frame)
            with self._lock:
                probabilities = np.asarray(self.model.predict_proba(matrix))
            score = float(probabilities[0, 1])
        except InvalidFeatures:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable("account-opening scoring failed") from exc
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ModelUnavailable("account-opening model returned an invalid probability")
        return score


class AmlModel:
    BASE = ("log_amt_paid", "log_amt_recv", "amount_ratio", "currency_mismatch", "same_bank",
            "self_transfer", "hour", "dow", "from_bank_freq", "to_bank_freq", "from_out_deg",
            "to_in_deg", "from_out_amt", "to_in_amt", "from_fan_out", "to_fan_in")
    REQUIRED = ("from_bank", "from_acct", "to_bank", "to_acct", "amt_recv", "recv_ccy",
                "amt_paid", "pay_ccy", "format", "ts")

    def __init__(self, model: Any, feature_names: list[str], maps: dict,
                 version: str, threshold: float) -> None:
        self.model = model
        self.feature_names = tuple(feature_names)
        self.maps = maps
        self.version = version
        self.threshold = threshold
        self._lock = threading.Lock()

    @classmethod
    def load(cls, directory: str | Path) -> "AmlModel":
        directory = Path(directory)
        meta = _load_metadata(directory)
        artifact_path = directory / "model.joblib"
        if not artifact_path.is_file():
            raise ModelUnavailable(f"model.joblib not found in {directory}")
        try:
            bundle = joblib.load(artifact_path)
            model = bundle["model"]
            if not hasattr(model, "predict_proba"):
                raise ModelUnavailable("AML estimator has no probability output")
            feature_names = list(bundle["feature_names"])
            maps = bundle["aggregate_maps"]
            version = str(meta["version"])
            threshold = _threshold(meta, ["results", meta["selected_model"], "calibration", "threshold"])
        except ModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable("AML artifact could not be loaded") from exc
        return cls(model, feature_names, maps, version, threshold)

    def _base(self, txn: Mapping[str, Any]) -> dict[str, float]:
        from_bank, to_bank = str(txn["from_bank"]), str(txn["to_bank"])
        from_acct, to_acct = str(txn["from_acct"]), str(txn["to_acct"])
        amt_paid, amt_recv = float(txn["amt_paid"]), float(txn["amt_recv"])
        if not math.isfinite(amt_paid) or not math.isfinite(amt_recv):
            raise InvalidFeatures("amounts must be finite")
        recv_ccy, pay_ccy = str(txn["recv_ccy"]), str(txn["pay_ccy"])
        ts = pd.to_datetime(txn["ts"])
        m = self.maps
        return {
            "log_amt_paid": float(np.log1p(max(amt_paid, 0.0))),
            "log_amt_recv": float(np.log1p(max(amt_recv, 0.0))),
            "amount_ratio": amt_paid / (abs(amt_recv) + 1.0),
            "currency_mismatch": float(recv_ccy != pay_ccy),
            "same_bank": float(from_bank == to_bank),
            "self_transfer": float(from_acct == to_acct),
            "hour": float(ts.hour),
            "dow": float(ts.dayofweek),
            "from_bank_freq": float(m["bank_freq"].get(from_bank, 0.0)),
            "to_bank_freq": float(m["bank_freq"].get(to_bank, 0.0)),
            "from_out_deg": float(m["out_deg"].get(from_acct, 0)),
            "to_in_deg": float(m["in_deg"].get(to_acct, 0)),
            "from_out_amt": float(np.log1p(m["out_amt"].get(from_acct, 0.0))),
            "to_in_amt": float(np.log1p(m["in_amt"].get(to_acct, 0.0))),
            "from_fan_out": float(m["fan_out"].get(from_acct, 0)),
            "to_fan_in": float(m["fan_in"].get(to_acct, 0)),
        }

    def score(self, txn: Mapping[str, Any] | None) -> float:
        if txn is None:
            raise InvalidFeatures("transaction is required")
        missing = [k for k in self.REQUIRED if k not in txn]
        if missing:
            raise InvalidFeatures(f"missing transaction fields: {missing}")
        try:
            base = self._base(txn)
        except (InvalidFeatures, ModelUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001
            raise InvalidFeatures(f"invalid transaction: {exc}") from exc
        fmt, recv, pay = str(txn["format"]), str(txn["recv_ccy"]), str(txn["pay_ccy"])
        vector: list[float] = []
        for name in self.feature_names:
            if name in base:
                vector.append(base[name])
            elif name.startswith("format_"):
                vector.append(float(fmt == name[len("format_"):]))
            elif name.startswith("recv_ccy_"):
                vector.append(float(recv == name[len("recv_ccy_"):]))
            elif name.startswith("pay_ccy_"):
                vector.append(float(pay == name[len("pay_ccy_"):]))
            else:
                raise ModelUnavailable(f"unknown AML feature {name!r}")
        try:
            matrix = np.asarray([vector], dtype=np.float64)
            with self._lock:
                probabilities = np.asarray(self.model.predict_proba(matrix))
            score = float(probabilities[0, 1])
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable("AML scoring failed") from exc
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ModelUnavailable("AML model returned an invalid probability")
        return score


class WebAttackModel:
    def __init__(self, pipeline: Any, version: str, threshold: float) -> None:
        self.pipeline = pipeline
        self.version = version
        self.threshold = threshold
        self._lock = threading.Lock()

    @classmethod
    def load(cls, directory: str | Path) -> "WebAttackModel":
        directory = Path(directory)
        meta = _load_metadata(directory)
        artifact_path = directory / "model.joblib"
        if not artifact_path.is_file():
            raise ModelUnavailable(f"model.joblib not found in {directory}")
        try:
            pipeline = joblib.load(artifact_path)
            if not hasattr(pipeline, "predict_proba"):
                raise ModelUnavailable("web-attack pipeline has no probability output")
            version = str(meta["version"])
            threshold = _threshold(meta, ["results", "tfidf_lr", "calibration", "threshold"])
        except ModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable("web-attack artifact could not be loaded") from exc
        return cls(pipeline, version, threshold)

    def score(self, text: Any) -> float:
        if not isinstance(text, str) or not text.strip():
            raise InvalidFeatures("text must be a non-empty string")
        try:
            with self._lock:
                probabilities = np.asarray(self.pipeline.predict_proba([text]))
            score = float(probabilities[0, 1])
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable("web-attack scoring failed") from exc
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ModelUnavailable("web-attack model returned an invalid probability")
        return score


class AuxLayerService:
    """Holds the optional auxiliary models and records per-layer metrics."""

    def __init__(self, account_opening: AccountOpeningModel | None = None,
                 aml: AmlModel | None = None, web_attack: WebAttackModel | None = None) -> None:
        self.account_opening = account_opening
        self.aml = aml
        self.web_attack = web_attack
        AUX_MODEL_LOADED.labels(layer="account_opening").set(1 if account_opening else 0)
        AUX_MODEL_LOADED.labels(layer="aml").set(1 if aml else 0)
        AUX_MODEL_LOADED.labels(layer="web_attack").set(1 if web_attack else 0)

    def status(self) -> dict[str, Any]:
        def info(model: Any) -> dict[str, Any]:
            return {"loaded": model is not None,
                    "version": model.version if model is not None else None,
                    "threshold": model.threshold if model is not None else None}
        return {"account_opening": info(self.account_opening),
                "aml": info(self.aml), "web_attack": info(self.web_attack)}

    def _record(self, layer: str, score: float, threshold: float, fallback: bool,
                reason: str | None, version: str, latency_ms: float) -> dict[str, Any]:
        decision = "CHALLENGE" if (fallback or score >= threshold) else "PASS"
        AUX_SCORES_TOTAL.labels(layer=layer, decision=decision, fallback=str(fallback).lower()).inc()
        AUX_LATENCY_MS.labels(layer=layer).observe(latency_ms)
        AUX_SCORE.labels(layer=layer).observe(score)
        return {"layer": layer, "score": round(score, 6), "decision": decision,
                "threshold": threshold, "model_version": version, "fallback": fallback,
                "reason": reason, "latency_ms": round(latency_ms, 3)}

    def score_account_opening(self, features: Mapping[str, Any] | None) -> dict[str, Any]:
        started = time.perf_counter()
        model = self.account_opening
        if model is None:
            return self._record("account_opening", 0.5, 0.5, True, "MODEL_UNAVAILABLE", "unavailable", (time.perf_counter() - started) * 1000)
        try:
            score = model.score(features)
        except InvalidFeatures as exc:
            return self._record("account_opening", 0.5, model.threshold, True, f"INVALID_FEATURES: {exc}", model.version, (time.perf_counter() - started) * 1000)
        except ModelUnavailable as exc:
            return self._record("account_opening", 0.5, model.threshold, True, f"MODEL_UNAVAILABLE: {exc}", model.version, (time.perf_counter() - started) * 1000)
        return self._record("account_opening", score, model.threshold, False, None, model.version, (time.perf_counter() - started) * 1000)

    def score_aml(self, txn: Mapping[str, Any] | None) -> dict[str, Any]:
        started = time.perf_counter()
        model = self.aml
        if model is None:
            return self._record("aml", 0.5, 0.5, True, "MODEL_UNAVAILABLE", "unavailable", (time.perf_counter() - started) * 1000)
        try:
            score = model.score(txn)
        except InvalidFeatures as exc:
            return self._record("aml", 0.5, model.threshold, True, f"INVALID_FEATURES: {exc}", model.version, (time.perf_counter() - started) * 1000)
        except ModelUnavailable as exc:
            return self._record("aml", 0.5, model.threshold, True, f"MODEL_UNAVAILABLE: {exc}", model.version, (time.perf_counter() - started) * 1000)
        return self._record("aml", score, model.threshold, False, None, model.version, (time.perf_counter() - started) * 1000)

    def score_web_attack(self, text: Any) -> dict[str, Any]:
        started = time.perf_counter()
        model = self.web_attack
        if model is None:
            return self._record("web_attack", 0.5, 0.5, True, "MODEL_UNAVAILABLE", "unavailable", (time.perf_counter() - started) * 1000)
        try:
            score = model.score(text)
        except InvalidFeatures as exc:
            return self._record("web_attack", 0.5, model.threshold, True, f"INVALID_FEATURES: {exc}", model.version, (time.perf_counter() - started) * 1000)
        except ModelUnavailable as exc:
            return self._record("web_attack", 0.5, model.threshold, True, f"MODEL_UNAVAILABLE: {exc}", model.version, (time.perf_counter() - started) * 1000)
        return self._record("web_attack", score, model.threshold, False, None, model.version, (time.perf_counter() - started) * 1000)


def load_aux_service() -> AuxLayerService:
    """Load whichever auxiliary artifacts are configured; absent ones fail closed."""
    import logging
    import os
    logger = logging.getLogger(__name__)
    base = Path(__file__).resolve().parents[1] / "training" / "artifacts"

    def _try(loader: Any, env: str, default: Path) -> Any:
        path = Path(os.environ.get(env, str(default)))
        try:
            return loader(path)
        except ModelUnavailable as exc:
            logger.warning("Auxiliary layer %s unavailable: %s", env, exc)
            return None

    return AuxLayerService(
        account_opening=_try(AccountOpeningModel.load, "ACCOUNT_OPENING_MODEL_DIR", base / "account_opening_fraud"),
        aml=_try(AmlModel.load, "AML_MODEL_DIR", base / "aml_laundering"),
        web_attack=_try(WebAttackModel.load, "WEB_ATTACK_MODEL_DIR", base / "web_attack_guard"),
    )