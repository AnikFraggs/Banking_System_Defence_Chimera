"""
CHIMERA AI Brain — GenAI-style cybersecurity triage microservice.

This is the "brain" the Java platform-api delegates risk scoring to over HTTP
(AiBrainClient expects /health and /v1/triage on this service). It combines:

  * a lightweight gradient-style feature-weighted risk model (no external model
    download required, so it deploys anywhere), and
  * a small retrieval-augmented knowledge base (RAG) of common attack classes,
    so every verdict is explained with a mitigation the manager can act on.

It runs fully offline. If an OPENAI_API_KEY / ANTHROPIC_API_KEY is present it
would be the natural place to add an LLM summary, but the service never depends
on it being reachable.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CHIMERA AI Brain", version="1.0.0")

# --- Retrieval knowledge base: attack class -> signature + mitigation ----------
KNOWLEDGE: List[Dict[str, Any]] = [
    {
        "id": "T1190",
        "name": "SQL Injection",
        "patterns": [r"('|%27).*(--|#)", r"\bunion\b.*\bselect\b", r"\bor\b\s+1\s*=\s*1", r";\s*drop\s+table"],
        "weight": 0.95,
        "mitigation": "Use parameterized queries; reject the request and rotate any exposed DB credentials.",
    },
    {
        "id": "T1059",
        "name": "Command / Script Injection",
        "patterns": [r"[;&|`]\s*(rm|curl|wget|bash|sh)\b", r"\$\(", r"<script", r"onerror\s*="],
        "weight": 0.9,
        "mitigation": "Escape shell/HTML output, apply allow-list input validation, and isolate the session.",
    },
    {
        "id": "T1566",
        "name": "Prompt Injection / Social Engineering",
        "patterns": [r"ignore (all|previous) instructions", r"you are now", r"reveal.*(system prompt|secret|key)",
                     r"\b999\b"],
        "weight": 0.85,
        "mitigation": "Strip untrusted instructions, never expose system context, require human step-up.",
    },
    {
        "id": "T1110",
        "name": "Brute Force / Credential Stuffing",
        "patterns": [r"(password|passwd|pwd)\s*=", r"login.*attempt", r"\b(admin|root)\b.*\b(admin|root|123456)\b"],
        "weight": 0.7,
        "mitigation": "Enforce rate limiting, lockout, and MFA on the affected identity.",
    },
    {
        "id": "T1071",
        "name": "Data Exfiltration",
        "patterns": [r"base64", r"exfiltrat", r"select \* from", r"dump.*(db|database|table)"],
        "weight": 0.8,
        "mitigation": "Quarantine the session, block egress, and audit recent reads on sensitive tables.",
    },
]


class TriageRequest(BaseModel):
    telemetry: Dict[str, Any] = {}
    include_llm_summary: bool = False


def _text_of(telemetry: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("payload", "purpose", "message", "detail", "text"):
        value = telemetry.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()


def _retrieve(text: str) -> List[Dict[str, Any]]:
    """RAG step: pull the attack classes whose signatures fire on this text."""
    hits: List[Dict[str, Any]] = []
    for entry in KNOWLEDGE:
        for pattern in entry["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                hits.append(entry)
                break
    return hits


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "model": "chimera-brain-heuristic-rag", "knowledge_entries": len(KNOWLEDGE)}


@app.post("/v1/triage")
def triage(req: TriageRequest) -> Dict[str, Any]:
    t = req.telemetry or {}
    text = _text_of(t)
    hits = _retrieve(text)

    # Feature-weighted risk: signature match strength + behavioral anomaly.
    signature_risk = max((h["weight"] for h in hits), default=0.0)
    anomaly = float(t.get("behavior_anomaly", 0.0) or 0.0)
    workload_invalid = t.get("entry_context") == "workload" and t.get("workload_identity_valid") is False

    raw = 2.4 * signature_risk + 1.6 * anomaly + (1.5 if workload_invalid else 0.0) - 1.2
    risk_score = round(_logistic(raw), 4)

    if risk_score >= 0.75 or workload_invalid:
        recommendation, requires_human = "isolate_session", True
    elif risk_score >= 0.5:
        recommendation, requires_human = "constrain", True
    elif risk_score >= 0.3:
        recommendation, requires_human = "step_up", False
    else:
        recommendation, requires_human = "allow", False

    threats = [
        {"technique_id": h["id"], "name": h["name"], "mitigation": h["mitigation"]}
        for h in hits
    ]
    summary = (
        f"Detected {len(threats)} threat signature(s): "
        + ", ".join(h["name"] for h in hits)
        if hits else "No known attack signature detected."
    )

    return {
        "risk_score": risk_score,
        "enforced_recommendation": recommendation,
        "requires_human_approval": requires_human,
        "detected_threats": threats,
        "manager_action": _manager_action(recommendation, threats),
        "summary": summary,
    }


def _manager_action(recommendation: str, threats: List[Dict[str, Any]]) -> str:
    if recommendation == "isolate_session":
        base = "Isolate the session now and review the audit trail."
    elif recommendation == "constrain":
        base = "Constrain the session to read-only and require human verification."
    elif recommendation == "step_up":
        base = "Trigger step-up authentication before allowing the action."
    else:
        base = "No action required; continue monitoring."
    if threats:
        base += " Recommended fix: " + threats[0]["mitigation"]
    return base
