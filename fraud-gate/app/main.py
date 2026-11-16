"""FastAPI entry point for CHIMERA's synchronous pre-capture fraud gate."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from .aux_layers import load_aux_service
from .card_model import CardModel, ModelUnavailable
from .decision_service import DecisionService
from .investigator import ExplanationPublisher
from .rolling_counters import RollingCounters
from .safe_lcb import SafeLcbError, SafeLcbPolicy, load_safe_lcb
from .schemas import ReadinessResponse, ScoreRequest, ScoreResponse

logger = logging.getLogger(__name__)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "creditcard_hgb.joblib"


class AccountOpeningRequest(BaseModel):
    features: dict


class AmlRequest(BaseModel):
    transaction: dict


class WebAttackRequest(BaseModel):
    text: str


def _load_step_up_policy() -> SafeLcbPolicy | None:
    path = os.environ.get("SAFE_LCB_POLICY_PATH")
    if not path:
        return None
    try:
        return load_safe_lcb(path)
    except SafeLcbError as exc:
        # A malformed tightening policy must never silently weaken friction.
        logger.error("Safe-LCB policy rejected: %s", exc)
        return None


def _load_rolling_counters() -> RollingCounters | None:
    if os.environ.get("GRAPH_COUNTERS_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return None
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        logger.error("Rolling graph counters disabled: %s", exc)
        return None
    return RollingCounters(client)


def create_app(
    *,
    card_model: CardModel | None = None,
    model_path: str | Path | None = None,
) -> FastAPI:
    """Build an app; direct card_model injection is intended for unit tests."""
    injected_model = card_model

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.model_load_error = None
        if injected_model is not None:
            app.state.card_model = injected_model
        else:
            path = model_path or os.environ.get("MODEL_ARTIFACT_PATH", str(DEFAULT_MODEL_PATH))
            try:
                # Loaded exactly once per process, never in the request path.
                app.state.card_model = CardModel.load(path)
            except ModelUnavailable as exc:
                app.state.card_model = None
                app.state.model_load_error = str(exc)
                logger.error("Fraud gate model unavailable: %s", exc)

        redis_url = os.environ.get("REDIS_URL")
        publisher = ExplanationPublisher(redis_url) if redis_url else None
        if publisher is not None:
            await publisher.start()
        app.state.explanation_publisher = publisher
        app.state.decision_service = DecisionService(
            app.state.card_model,
            explanation_publisher=publisher,
            step_up_policy=_load_step_up_policy(),
            rolling_counters=_load_rolling_counters(),
        )
        # Optional auxiliary defence layers; absent artifacts fail closed to CHALLENGE.
        app.state.aux_service = load_aux_service()
        yield
        if publisher is not None:
            await publisher.close()

    app = FastAPI(
        title="CHIMERA Checkout Shield Fraud Gate",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/ready", response_model=ReadinessResponse)
    def ready() -> JSONResponse:
        model = app.state.card_model
        payload = ReadinessResponse(
            ready=model is not None,
            model_loaded=model is not None,
            model_version=model.version if model is not None else None,
            error=app.state.model_load_error,
        )
        return JSONResponse(
            status_code=200 if model is not None else 503,
            content=payload.model_dump(mode="json"),
        )

    @app.post("/score/pre-capture", response_model=ScoreResponse)
    async def pre_capture(request: ScoreRequest) -> ScoreResponse:
        return await app.state.decision_service.score(request)

    @app.get("/ready/aux")
    def ready_aux() -> JSONResponse:
        status = app.state.aux_service.status()
        any_loaded = any(layer["loaded"] for layer in status.values())
        return JSONResponse(status_code=200 if any_loaded else 503, content=status)

    @app.post("/score/account-opening")
    def score_account_opening(request: AccountOpeningRequest) -> JSONResponse:
        result = app.state.aux_service.score_account_opening(request.features)
        return JSONResponse(status_code=200, content=result)

    @app.post("/score/aml")
    def score_aml(request: AmlRequest) -> JSONResponse:
        result = app.state.aux_service.score_aml(request.transaction)
        return JSONResponse(status_code=200, content=result)

    @app.post("/score/web-attack")
    def score_web_attack(request: WebAttackRequest) -> JSONResponse:
        result = app.state.aux_service.score_web_attack(request.text)
        return JSONResponse(status_code=200, content=result)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
