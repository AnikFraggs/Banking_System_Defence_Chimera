"""Async gRPC transport sharing the REST decision and fail-closed scoring path."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Any

import grpc
from prometheus_client import start_http_server
from pydantic import ValidationError

from .card_model import CardModel, ModelUnavailable
from .decision_service import DecisionService
from .grpc_generated import fraud_gate_pb2, fraud_gate_pb2_grpc
from .investigator import ExplanationPublisher
from .main import DEFAULT_MODEL_PATH, _load_rolling_counters, _load_step_up_policy
from .schemas import ScoreRequest

logger = logging.getLogger(__name__)


def request_from_proto(message: fraud_gate_pb2.ScoreRequest) -> ScoreRequest:
    evidence = None
    if message.HasField("evidence"):
        evidence = {
            "metadata": dict(message.evidence.metadata),
            "ocr_text": message.evidence.ocr_text or None,
            "generator_marker": message.evidence.generator_marker or None,
            "pixel_residual": message.evidence.pixel_residual,
            "image_payload": (
                base64.b64encode(message.evidence.image_payload).decode("ascii")
                if message.evidence.image_payload else None
            ),
        }
    context: dict[str, Any] = {}
    if message.HasField("context"):
        context = {
            "step_up_verified": message.context.step_up_verified,
            "prior_evidence_score": message.context.prior_evidence_score,
            "scenario_id": message.context.scenario_id or None,
        }
    return ScoreRequest.model_validate({
        "order_id": message.order_id,
        "paypal_authorization_id": message.paypal_authorization_id or None,
        "mode": message.mode,
        "amount": message.amount,
        "currency": message.currency,
        "timestamp": message.timestamp,
        "rail": message.rail,
        "card_features": dict(message.card_features),
        "telemetry": {
            "keystroke_intervals_ms": list(message.telemetry.keystroke_intervals_ms),
            "keystroke_dwell_ms": list(message.telemetry.keystroke_dwell_ms),
            "mouse_movements": [
                {"x": item.x, "y": item.y, "interval_ms": item.interval_ms}
                for item in message.telemetry.mouse_movements
            ],
        },
        "history": [
            {
                "device_id": item.device_id,
                "destination": item.destination,
                "amount": item.amount,
                "timestamp": item.timestamp,
            }
            for item in message.history
        ],
        "evidence": evidence,
        "context": context,
    })


class FraudGateServicer(fraud_gate_pb2_grpc.FraudGateServicer):
    def __init__(self, decisions: DecisionService) -> None:
        self.decisions = decisions

    async def ScorePreCapture(self, request, context):
        try:
            parsed = request_from_proto(request)
            response = await self.decisions.score(parsed)
        except ValidationError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc)[:2048])
        except Exception as exc:
            logger.exception("Unexpected gRPC decision failure")
            await context.abort(grpc.StatusCode.INTERNAL, "fraud gate decision failed")
        return fraud_gate_pb2.ScoreResponse(
            decision_id=response.decision_id,
            score=response.score,
            action=response.action.value,
            reasons=[
                {
                    "code": reason.code,
                    "message": reason.message,
                    "component": reason.component,
                    "score": reason.score,
                }
                for reason in response.reasons
            ],
            component_scores=response.component_scores,
            model_version=response.model_version,
            feature_hash=response.feature_hash,
            fallback=response.fallback,
            latency_ms=response.latency_ms,
        )


def create_grpc_server(decisions: DecisionService) -> grpc.aio.Server:
    server = grpc.aio.server(options=(
        ("grpc.max_receive_message_length", 4_000_000),
        ("grpc.max_send_message_length", 1_000_000),
    ))
    fraud_gate_pb2_grpc.add_FraudGateServicer_to_server(
        FraudGateServicer(decisions), server
    )
    return server


async def serve() -> None:
    path = os.environ.get("MODEL_ARTIFACT_PATH", str(DEFAULT_MODEL_PATH))
    try:
        model = CardModel.load(Path(path))
        load_error = None
    except ModelUnavailable as exc:
        model = None
        load_error = str(exc)
        logger.error("Fraud gate model unavailable: %s", exc)
    redis_url = os.environ.get("REDIS_URL")
    publisher = ExplanationPublisher(redis_url) if redis_url else None
    if publisher is not None:
        await publisher.start()
    server = create_grpc_server(DecisionService(
        model,
        explanation_publisher=publisher,
        step_up_policy=_load_step_up_policy(),
        rolling_counters=_load_rolling_counters(),
    ))
    target = os.environ.get("GRPC_TARGET", "0.0.0.0:50051")
    if server.add_insecure_port(target) == 0:
        raise RuntimeError(f"could not bind gRPC server to {target}")
    await server.start()
    metrics_port = int(os.environ.get("METRICS_PORT", "8081"))
    start_http_server(metrics_port)
    logger.info("Fraud gate gRPC listening on %s; model_error=%s", target, load_error)
    logger.info("Fraud gate gRPC metrics exposed on :%d/metrics", metrics_port)
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=5)
        if publisher is not None:
            await publisher.close()


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(serve())


if __name__ == "__main__":
    main()
