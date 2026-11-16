"""Asynchronous constrained prosecutor/defense debate and deterministic judge."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canary_guard import CanaryGuard, harvest_row
from .canonical import Scalar, canonicalize_telemetry, telemetry_from_job
from .case_matching import (
    CaseMatch,
    CaseMatcher,
    CaseSearchResult,
    RetrievalMetadata,
    empty_search_result,
    query_text,
)

logger = logging.getLogger(__name__)
Role = Literal["PROSECUTOR", "DEFENSE"]
Stance = Literal["FRAUD", "BENIGN", "INCONCLUSIVE"]
Backend = Callable[[Mapping[str, Any]], Awaitable[str | Mapping[str, Any] | None]]


def _build_canary_guard() -> CanaryGuard | None:
    """Per-call HMAC canary guard, enabled only when CANARY_SECRET (>=16 bytes) is set.

    Escalate-only: a confirmed leak discards the LLM argument and forces the informational
    delta to 0; it never relaxes a decision. Absent/short secret => disabled (no behavior change).
    """
    secret = os.environ.get("CANARY_SECRET", "")
    if len(secret.encode("utf-8")) < 16:
        return None
    try:
        return CanaryGuard(secret=secret.encode("utf-8"))
    except ValueError:
        return None


_canary_guard = _build_canary_guard()
_canary_harvest_path = os.environ.get("CANARY_HARVEST_PATH", "out/canary_hits.jsonl")


def _harvest_canary_hit(inbound_text: str, scan) -> None:
    try:
        path = Path(_canary_harvest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(harvest_row(inbound_text, scan), ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Could not harvest canary hit: %s", exc)


class DebateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class PartyArgument(DebateModel):
    role: Role
    stance: Stance
    confidence: float = Field(ge=0, le=0.95)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(min_length=1, max_length=2000)

    @field_validator("evidence_refs")
    @classmethod
    def bounded_unique_references(cls, references: list[str]) -> list[str]:
        if len(set(references)) != len(references):
            raise ValueError("evidence references must be unique")
        for reference in references:
            if not reference or len(reference) > 64:
                raise ValueError("evidence references must contain 1 to 64 characters")
            if not all(character.isalnum() or character in "_.:-" for character in reference):
                raise ValueError("evidence references contain unsupported characters")
        return references

    @model_validator(mode="after")
    def calibrated_role_and_stance(self) -> "PartyArgument":
        if self.role == "PROSECUTOR" and self.stance == "BENIGN":
            raise ValueError("the prosecutor may only argue FRAUD or INCONCLUSIVE")
        if self.role == "DEFENSE" and self.stance == "FRAUD":
            raise ValueError("the defense may only argue BENIGN or INCONCLUSIVE")
        if self.stance != "INCONCLUSIVE" and self.confidence < 0.5:
            raise ValueError("a decisive stance requires confidence of at least 0.5")
        return self


class JudgeDecision(DebateModel):
    outcome: Literal["FRAUD", "BENIGN", "INCONCLUSIVE"]
    confidence: float = Field(ge=0, le=0.95)
    rationale: str = Field(min_length=1, max_length=2000)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=8)


class DebateResult(DebateModel):
    decision_id: str = Field(min_length=1, max_length=128)
    order_id: str | None = Field(default=None, min_length=1, max_length=128)
    prosecutor: PartyArgument
    defense: PartyArgument
    judge: JudgeDecision
    explanation: str = Field(min_length=1, max_length=4096)
    score_delta: float | None = Field(default=None, ge=-0.05, le=0.05)
    canary_escalated: bool = Field(default=False)
    matched_cases: list[CaseMatch] = Field(default_factory=list, max_length=10)
    retrieval: RetrievalMetadata


def clamp_score_delta(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("score delta must be finite")
    return max(-0.05, min(0.05, number))


def _number(features: Mapping[str, Scalar], *keys: str) -> float:
    for key in keys:
        value = features.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number):
                return number
    return 0.0


def _flag(features: Mapping[str, Scalar], key: str) -> bool:
    value = features.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "yes", "1"}


def _evidence_codes(job: Mapping[str, Any]) -> list[str]:
    reasons = job.get("reasons")
    if not isinstance(reasons, list):
        return []
    return [
        str(reason["code"])[:64]
        for reason in reasons[:8]
        if isinstance(reason, Mapping) and reason.get("code")
    ]


def local_argument(
    role: Role, job: Mapping[str, Any], features: Mapping[str, Scalar]
) -> PartyArgument:
    """Deterministic fallback constrained to the role's assigned thesis."""
    fan_out = _number(features, "fan_out", "device_fanout_1h")
    graph_risk = max(_number(features, "graph_score"), min(1.0, fan_out / 6.0))
    bot_score = _number(features, "bot_score")
    hgb_score = _number(features, "hgb_score")
    evidence_score = _number(features, "evidence_score")
    graph_anomaly = graph_risk >= 0.55 or fan_out >= 4
    biometric_anomaly = bot_score >= 0.60
    other_anomaly = hgb_score >= 0.55 or evidence_score >= 0.60 or _flag(features, "l4_flag")
    reason_codes = _evidence_codes(job)
    available = [key for key in features if key in {
        "fan_out", "device_fanout_1h", "graph_score", "bot_score", "hgb_score",
        "evidence_score", "l4_flag", "step_up_verified",
    }]
    references = list(dict.fromkeys([*available, *reason_codes]))[:8]
    if not references:
        references = ["decision_score"]

    if role == "PROSECUTOR":
        coordinated = graph_anomaly and biometric_anomaly
        supporting = sum((graph_anomaly, biometric_anomaly, other_anomaly))
        if coordinated:
            confidence = min(0.95, 0.60 + 0.10 * supporting + 0.10 * max(graph_risk, bot_score))
            stance: Stance = "FRAUD"
            summary = (
                "Graph dispersion/velocity and session automation are anomalous together, "
                "which is consistent with coordinated account control rather than isolated friction."
            )
        else:
            confidence = 0.55 if supporting else 0.5
            stance = "INCONCLUSIVE"
            summary = (
                "The prosecution finds insufficient joint graph and biometric evidence for "
                "coordinated fraud; isolated model or artifact signals remain non-diagnostic."
            )
        return PartyArgument(
            role=role, stance=stance, confidence=confidence,
            evidence_refs=references, summary=summary,
        )

    benign_friction = not (graph_anomaly and biometric_anomaly)
    verified = _flag(features, "step_up_verified")
    if benign_friction:
        confidence = min(0.90, 0.60 + (0.10 if verified else 0.0) + 0.05 * (not other_anomaly))
        stance = "BENIGN"
        summary = (
            "The defense attributes the review to benign customer friction: the available "
            "signals do not establish both coordinated graph behavior and automated control."
        )
    else:
        confidence = 0.55
        stance = "INCONCLUSIVE"
        summary = (
            "Joint graph and automation anomalies weaken a benign-friction explanation, "
            "although they do not alone establish the customer's intent."
        )
    return PartyArgument(
        role=role, stance=stance, confidence=confidence,
        evidence_refs=references, summary=summary,
    )


def adjudicate(
    prosecutor: PartyArgument,
    defense: PartyArgument,
    matched_cases: list[CaseMatch] | None = None,
) -> JudgeDecision:
    """Apply a fixed rule; no model can choose a settlement action."""
    fraud_support = prosecutor.confidence if prosecutor.stance == "FRAUD" else 0.0
    benign_support = defense.confidence if defense.stance == "BENIGN" else 0.0
    matches = matched_cases or []
    historical_weight = sum(match.score for match in matches)
    historical_margin = (
        sum(
            match.score * (1.0 if match.verdict == "FRAUD" else -1.0)
            for match in matches
            if match.verdict in {"FRAUD", "BENIGN"}
        ) / historical_weight
        if historical_weight
        else 0.0
    )
    margin = fraud_support - benign_support + 0.15 * historical_margin
    if fraud_support >= 0.55 and margin >= 0.15:
        outcome: Stance = "FRAUD"
        confidence = min(0.95, 0.50 + margin / 2.0)
        rationale = "The prosecutor's calibrated fraud thesis exceeds the deterministic support margin."
        evidence = prosecutor.evidence_refs
    elif benign_support >= 0.55 and margin <= -0.15:
        outcome = "BENIGN"
        confidence = min(0.95, 0.50 + abs(margin) / 2.0)
        rationale = "The defense's calibrated benign-friction thesis exceeds the deterministic support margin."
        evidence = defense.evidence_refs
    else:
        outcome = "INCONCLUSIVE"
        confidence = min(0.95, 0.50 + (1.0 - min(1.0, abs(margin))) * 0.25)
        rationale = "The constrained arguments and historical matches do not meet either deterministic support margin."
        evidence = list(dict.fromkeys([*prosecutor.evidence_refs, *defense.evidence_refs]))
    return JudgeDecision(
        outcome=outcome,
        confidence=round(confidence, 6),
        rationale=rationale,
        supporting_evidence=evidence[:8],
    )


def informational_delta(judge: JudgeDecision) -> float:
    if judge.outcome == "INCONCLUSIVE":
        return 0.0
    direction = 1.0 if judge.outcome == "FRAUD" else -1.0
    return round(clamp_score_delta(direction * (judge.confidence - 0.5) * 0.1), 6)


def _parse_argument(
    raw: str | Mapping[str, Any] | None,
    role: Role,
    allowed_references: set[str],
) -> PartyArgument:
    if isinstance(raw, str):
        decoded = json.loads(raw)
    else:
        decoded = raw
    if not isinstance(decoded, Mapping):
        raise ValueError("party backend must return a JSON object")
    argument = PartyArgument.model_validate(decoded)
    if argument.role != role:
        raise ValueError("party backend returned the wrong role")
    unknown = set(argument.evidence_refs).difference(allowed_references)
    if unknown:
        raise ValueError(f"party backend cited unknown evidence: {sorted(unknown)}")
    return argument


async def _party_call(
    role: Role,
    job: Mapping[str, Any],
    features: Mapping[str, Scalar],
    canonical: str,
    backend: Backend | None,
    canary_leaks: list[str] | None = None,
) -> PartyArgument:
    fallback = local_argument(role, job, features)
    if backend is None:
        return fallback
    references = set(features).union(_evidence_codes(job))
    references.add("decision_score")
    instruction = (
        "Argue coordinated fraud using graph/biometric anomalies."
        if role == "PROSECUTOR"
        else "Argue benign customer friction and challenge unsupported fraud inferences."
    )
    request = {
        "role": role,
        "instruction": instruction,
        "decision_id": str(job.get("decision_id", "")),
        "order_id": str(job.get("order_id", "")),
        "score": job.get("score", 0.0),
        "reasons": job.get("reasons", []),
        "telemetry": canonical,
        "allowed_evidence_refs": sorted(references),
        "response_schema": {
            "role": role,
            "stance": "FRAUD|INCONCLUSIVE" if role == "PROSECUTOR" else "BENIGN|INCONCLUSIVE",
            "confidence": "0..0.95; decisive stances require >=0.5",
            "evidence_refs": "at most 8 entries copied from allowed_evidence_refs",
            "summary": "1..2000 characters; no settlement action field",
        },
    }
    canary = None
    if _canary_guard is not None:
        canary = _canary_guard.issue(str(job.get("decision_id", "")) or role)
        request["instruction"] = _canary_guard.plant(instruction, canary)
    try:
        raw = await backend(request)
        if canary is not None:
            raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            scan = _canary_guard.scan(raw_text, [canary])
            if scan.leaked:
                logger.warning(
                    "CANARY LEAK in %s backend output (kinds=%s); discarding LLM argument and escalating.",
                    role, scan.kinds,
                )
                inbound = f"{job.get('investigation_text', '')}\n{canonical}".strip()
                _harvest_canary_hit(inbound, scan)
                if canary_leaks is not None:
                    canary_leaks.append(role)
                return fallback
        return _parse_argument(raw, role, references)
    except Exception as exc:
        logger.warning("%s backend failed validation; using local argument: %s", role, exc)
        return fallback


async def _retrieve(
    job: Mapping[str, Any],
    features: Mapping[str, Scalar],
    case_memory: Any,
    case_matcher: CaseMatcher | None,
) -> CaseSearchResult:
    text = query_text(str(job.get("investigation_text", "")), features)
    try:
        if case_memory is not None:
            return await case_memory.match(text, features, limit=5)
        if case_matcher is not None:
            return await case_matcher.match(text, features, (), limit=5)
        return empty_search_result()
    except Exception as exc:
        logger.warning("Case retrieval unavailable: %s", exc)
        return empty_search_result(error="case retrieval unavailable")


async def run_debate(
    job: Mapping[str, Any],
    *,
    backend: Backend | None = None,
    case_matcher: CaseMatcher | None = None,
    case_memory: Any = None,
) -> DebateResult:
    """Run exactly two constrained calls concurrently, then adjudicate locally."""
    features = telemetry_from_job(job)
    canonical = canonicalize_telemetry(features)
    canary_leaks: list[str] = []
    prosecutor_task = _party_call("PROSECUTOR", job, features, canonical, backend, canary_leaks)
    defense_task = _party_call("DEFENSE", job, features, canonical, backend, canary_leaks)
    retrieval_task = _retrieve(job, features, case_memory, case_matcher)
    prosecutor, defense, search = await asyncio.gather(
        prosecutor_task, defense_task, retrieval_task
    )
    judge = adjudicate(prosecutor, defense, search.matches)
    delta = informational_delta(judge)
    escalated = bool(canary_leaks)
    if escalated:
        delta = 0.0
    explanation = (
        f"{judge.rationale} Outcome {judge.outcome} at confidence {judge.confidence:.3f}. "
        "This asynchronous review is informational only; the pre-capture score and settlement are unchanged."
    )
    if escalated:
        explanation += (
            f" Canary leak confirmed in {', '.join(canary_leaks)} backend output; the LLM argument was "
            "discarded, the informational delta forced to 0, and the case escalated for review."
        )
    order_id = str(job.get("order_id", "")).strip() or None
    return DebateResult(
        decision_id=str(job.get("decision_id", "")).strip() or "unknown",
        order_id=order_id,
        prosecutor=prosecutor,
        defense=defense,
        judge=judge,
        explanation=explanation,
        score_delta=delta,
        canary_escalated=escalated,
        matched_cases=search.matches,
        retrieval=search.retrieval,
    )
