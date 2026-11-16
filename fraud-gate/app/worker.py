"""Redis Stream consumer: asynchronous prosecutor/defense debate and case memory.

Every emitted result is informational only. Debate, retrieval, LoRA verdicts, and
the ±0.05 score delta can never change a pre-capture score or settlement action.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .case_matching import CaseMatcher, matcher_from_environment
from .case_memory import RedisCaseMemory, SettledOrderError
from .debate import DebateResult, run_debate
from .investigator import EXPLANATION_STREAM, deterministic_explanation

logger = logging.getLogger(__name__)
GROUP = "fraud-gate-investigators"
VERDICT_GROUP = "fraud-gate-case-memory"
RESULT_STREAM = "fraud-gate:explanations:results"
VERDICT_STREAM = "fraud-gate:analyst-verdicts"
Backend = Callable[[Mapping[str, Any]], Awaitable[str | Mapping[str, Any] | None]]
EXPLANATIONS_TOTAL = Counter("chimera_fraud_gate_explanations_total", "Published asynchronous explanation results.", ["mode"])
MATCHED_CASES_TOTAL = Counter("chimera_fraud_gate_matched_cases_total", "Historical cases retrieved during successful debates.")
LLM_DELTA = Histogram("chimera_fraud_gate_llm_delta", "Informational-only debate delta; never changes settlement.", buckets=(-.05, -.025, 0, .025, .05))
LLM_DELTA_LAST = Gauge("chimera_fraud_gate_llm_delta_last", "Last published informational delta; meaningful only after an observation.")
LLM_DELTA_OUT_OF_BOUNDS = Counter("chimera_fraud_gate_llm_delta_out_of_bounds_total", "Published deltas outside the inclusive -0.05 to +0.05 bounds.")
CANARY_ESCALATIONS = Counter("chimera_fraud_gate_canary_escalations_total", "Confirmed canary leaks in async LLM output; argument discarded, delta forced to 0, case escalated.")
for mode in ("deterministic", "backend_configured", "fallback"):
    EXPLANATIONS_TOTAL.labels(mode=mode)


def _decode_job(fields: Mapping[Any, Any]) -> dict[str, Any]:
    job: dict[str, Any] = {}
    for raw_key, raw_value in fields.items():
        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
        value = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else raw_value
        job[key] = value
    try:
        job["score"] = float(job.get("score", 0.0))
        job["reasons"] = json.loads(str(job.get("reasons", "[]")))
    except (TypeError, ValueError, json.JSONDecodeError):
        job["score"] = 0.0
        job["reasons"] = []
    return job


async def generate_explanation(
    job: Mapping[str, Any], backend: Backend | None = None
) -> str:
    """Use an optional asynchronous backend, with a deterministic safe fallback."""
    fallback = deterministic_explanation(job)
    if backend is None:
        return fallback
    try:
        generated = await backend(job)
        return generated.strip() if isinstance(generated, str) and generated.strip() else fallback
    except Exception as exc:
        logger.warning("Explanation backend failed; using template: %s", exc)
        return fallback


def _result_fields(decision_id: str, order_id: str, debate: DebateResult) -> dict[str, str]:
    payload = {
        "decision_id": decision_id,
        "order_id": order_id,
        "judge_outcome": debate.judge.outcome,
        "judge_confidence": debate.judge.confidence,
        "score_delta": debate.score_delta,
        "matched_cases": len(debate.matched_cases),
        "retrieval_backend": debate.retrieval.backend,
        "explanation": debate.explanation,
    }
    return {
        "decision_id": decision_id,
        "order_id": order_id,
        "explanation": debate.explanation,
        "payload": json.dumps(payload, separators=(",", ":")),
    }


async def _consume_verdicts(
    redis_client: Any, memory: RedisCaseMemory, once: bool
) -> None:
    try:
        await redis_client.xgroup_create(
            VERDICT_STREAM, VERDICT_GROUP, id="0", mkstream=True
        )
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    batches = await redis_client.xreadgroup(
        VERDICT_GROUP,
        socket.gethostname(),
        {VERDICT_STREAM: ">"},
        count=10,
        block=100 if once else 5_000,
    )
    for _stream, messages in batches or []:
        for message_id, fields in messages:
            job = _decode_job(fields)
            order_id = str(job.get("order_id", "")).strip()
            verdict = str(job.get("verdict", "")).strip().upper()
            case_id = str(job.get("case_id", "")).strip()
            text = str(job.get("analysis", "")).strip()
            if not order_id or verdict not in {"FRAUD", "BENIGN", "INCONCLUSIVE"}:
                await redis_client.xack(VERDICT_STREAM, VERDICT_GROUP, message_id)
                continue
            try:
                await memory.update_from_analyst_verdict(
                    order_id=order_id,
                    decision_id=case_id or order_id,
                    verdict=verdict,
                    telemetry={},
                    text=text,
                )
            except SettledOrderError:
                logger.info("Ignoring duplicate analyst verdict for order %s", order_id)
            except Exception as exc:
                logger.warning("Could not store analyst verdict for order %s: %s", order_id, exc)
                continue
            await redis_client.xack(VERDICT_STREAM, VERDICT_GROUP, message_id)


async def run_worker(
    redis_client: Any = None,
    *,
    backend: Backend | None = None,
    once: bool = False,
    matcher: CaseMatcher | None = None,
) -> None:
    if redis_client is None:
        from redis.asyncio import Redis

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        redis_client = Redis.from_url(redis_url, decode_responses=True)
    memory = RedisCaseMemory(redis_client, matcher=matcher)
    consumer = os.environ.get("WORKER_NAME", socket.gethostname())
    try:
        await redis_client.xgroup_create(EXPLANATION_STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    while True:
        batches = await redis_client.xreadgroup(
            GROUP,
            consumer,
            {EXPLANATION_STREAM: ">"},
            count=10,
            block=100 if once else 5_000,
        )
        for _stream, messages in batches or []:
            for message_id, fields in messages:
                job = _decode_job(fields)
                decision_id = str(job.get("decision_id", ""))
                order_id = str(job.get("order_id", ""))
                try:
                    debate = await run_debate(
                        job,
                        backend=backend,
                        case_matcher=matcher,
                        case_memory=memory,
                    )
                    fields_out = _result_fields(decision_id, order_id, debate)
                    mode = "backend_configured" if backend else "deterministic"
                except Exception as exc:
                    logger.warning("Debate failed; using template explanation: %s", exc)
                    mode = "fallback"
                    fields_out = {
                        "decision_id": decision_id,
                        "order_id": order_id,
                        "explanation": deterministic_explanation(job),
                    }
                await redis_client.xadd(
                    RESULT_STREAM,
                    fields_out,
                    maxlen=10_000,
                    approximate=True,
                )
                EXPLANATIONS_TOTAL.labels(mode=mode).inc()
                if mode != "fallback":
                    MATCHED_CASES_TOTAL.inc(len(debate.matched_cases))
                    LLM_DELTA.observe(debate.score_delta)
                    LLM_DELTA_LAST.set(debate.score_delta)
                    if not -.05 <= debate.score_delta <= .05:
                        LLM_DELTA_OUT_OF_BOUNDS.inc()
                    if getattr(debate, "canary_escalated", False) is True:
                        CANARY_ESCALATIONS.inc()
                await redis_client.xack(EXPLANATION_STREAM, GROUP, message_id)
        # Verdict feedback updates historical memory only; it never reads
        # or alters an in-flight decision.
        await _consume_verdicts(redis_client, memory, once)
        if once:
            return


def _http_backend(url: str) -> Backend:
    async def call(job: Mapping[str, Any]) -> str | None:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(url, json=dict(job))
            response.raise_for_status()
            body = response.json()
            return body.get("explanation") if isinstance(body, dict) else None

    return call


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume asynchronous fraud-gate explanation jobs")
    parser.add_argument("--once", action="store_true", help="Process one Redis read and exit")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    backend_url = os.environ.get("EXPLANATION_BACKEND_URL")
    backend = _http_backend(backend_url) if backend_url else None
    matcher = matcher_from_environment()
    if not args.once:
        start_http_server(int(os.environ.get("METRICS_PORT", "8084")))
    asyncio.run(run_worker(backend=backend, once=args.once, matcher=matcher))


if __name__ == "__main__":
    main()
