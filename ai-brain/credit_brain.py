"""Credit-application fraud brain: CPN synthetic identities, tradeline boosting,
credit sweeps and seller-operated "approval packages".

Grounded in Resistant AI's credit-boost fraud research. Training and serving share
``featurize`` so there is no train/serve skew. Inference is stdlib-only. The serving model
is credit_brain_v3.json: LightGBM trees (training/train_credit_brain_v3.py) traversed in pure
Python, with reason codes from exact tree-path attribution. Standardized-LR JSON files
(v1/v2, training/train_credit_brain.py) still load for rollback via CREDIT_BRAIN_MODEL_PATH.

Policy: the brain never auto-declines. It routes to standard checks, step-up
verification, or manual review; a human makes adverse decisions. If the model file
is missing the brain fails closed to manual review (never approve).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

PRODUCTS = ["credit_card", "bnpl", "personal_loan", "auto_loan", "apartment_rental", "mortgage"]
SHALLOW_PRODUCTS = {"credit_card", "bnpl", "apartment_rental"}
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "credit_brain_v3.json"

FEATURES: List[str] = [
    "identity_gap_years_log", "id_first_seen_log", "file_age_log", "thin_file", "au_ratio",
    "au_added_90d_log", "seasoning_gap_log", "au_limit_log", "score_norm", "score_jump",
    "disputes_log", "derogs_removed_log", "inquiries_log", "unknown_furnisher_primaries",
    "ecbsv_match", "ecbsv_no_match", "id_linked_other_identity", "id_deceased_record",
    "income_verified", "income_verify_failed", "doc_tamper_score", "loan_to_income_log",
    "asset_to_income_log", "address_mismatch", "phone_age_log", "email_age_log",
    "device_extra_identities_log", "thin_file_x_score",
] + [f"product_{p}" for p in PRODUCTS]


def _f(app: Mapping[str, Any], key: str) -> float:
    return float(app.get(key) or 0.0)


def identity_gap_years(app: Mapping[str, Any]) -> float:
    """Adult years with no trace of this identity; large for CPNs and for recent immigrants."""
    return max(0.0, _f(app, "applicant_age") - 18.0 - _f(app, "id_first_seen_years_ago"))


def seasoning_gap_months(app: Mapping[str, Any]) -> float:
    """Tradeline history older than the file itself: inherited via authorized-user slots."""
    return max(0.0, _f(app, "oldest_tradeline_months") - _f(app, "file_age_months"))


def featurize(app: Mapping[str, Any]) -> List[float]:
    file_age = _f(app, "file_age_months")
    thin = 1.0 if file_age < 24 else 0.0
    score_norm = (_f(app, "credit_score") - 650.0) / 100.0
    income = max(_f(app, "stated_monthly_income"), 1.0)
    product = str(app.get("product"))
    feats = [
        math.log1p(identity_gap_years(app)),
        math.log1p(_f(app, "id_first_seen_years_ago")),
        math.log1p(file_age),
        thin,
        _f(app, "n_au_tradelines") / max(1.0, _f(app, "n_tradelines")),
        math.log1p(_f(app, "au_added_90d")),
        math.log1p(seasoning_gap_months(app)),
        math.log1p(_f(app, "au_total_limit")),
        score_norm,
        _f(app, "score_delta_90d") / 100.0,
        math.log1p(_f(app, "disputes_90d")),
        math.log1p(_f(app, "derogs_removed_90d")),
        math.log1p(_f(app, "inquiries_6m")),
        _f(app, "unknown_furnisher_primaries"),
        1.0 if app.get("ecbsv_status") == "match" else 0.0,
        1.0 if app.get("ecbsv_status") == "no_match" else 0.0,
        _f(app, "id_linked_other_identity"),
        _f(app, "id_deceased_record"),
        1.0 if app.get("income_verification") == "verified" else 0.0,
        1.0 if app.get("income_verification") == "failed" else 0.0,
        _f(app, "doc_tamper_score"),
        math.log1p(_f(app, "requested_amount") / income),
        math.log1p(_f(app, "asset_price") / (12.0 * income)),
        0.0 if _f(app, "address_matches_bureau") >= 1 else 1.0,
        math.log1p(_f(app, "phone_age_days")),
        math.log1p(_f(app, "email_age_days")),
        math.log1p(max(0.0, _f(app, "device_identities_30d") - 1.0)),
        score_norm * thin,
    ]
    feats += [1.0 if product == p else 0.0 for p in PRODUCTS]
    return feats


# --- Red-flag knowledge base (article-grounded, each with a concrete mitigation) ---
RED_FLAGS: List[Dict[str, Any]] = [
    {"id": "CB-CPN-01", "name": "Recently issued identity on an adult applicant", "hard": False,
     "test": lambda a: identity_gap_years(a) >= 8 and _f(a, "id_first_seen_years_ago") < 3,
     "mitigation": "Run a consent-based eCBSV SSN/name/DOB check and documentary ID. Recent immigrants "
                   "legitimately match this pattern, so never decline on it alone."},
    {"id": "CB-CPN-02", "name": "Identifier linked to another identity", "hard": True,
     "test": lambda a: _f(a, "id_linked_other_identity") >= 1,
     "mitigation": "Manual review: the identifier appears under a different person, consistent with a "
                   "CPN built on a borrowed or child's SSN."},
    {"id": "CB-CPN-03", "name": "eCBSV returned no match", "hard": True,
     "test": lambda a: a.get("ecbsv_status") == "no_match",
     "mitigation": "Manual review with documentary SSN proof; a no-match can also be a name change or "
                   "data-entry error, so verify before any adverse action."},
    {"id": "CB-CPN-04", "name": "Identifier tied to a death record", "hard": True,
     "test": lambda a: _f(a, "id_deceased_record") >= 1,
     "mitigation": "Manual review and identity-theft escalation."},
    {"id": "CB-TL-01", "name": "Authorized-user tradeline stacking", "hard": False,
     "test": lambda a: _f(a, "n_au_tradelines") >= 3 or _f(a, "au_added_90d") >= 2,
     "mitigation": "Re-score excluding authorized-user tradelines; purchased AU slots add limit and age "
                   "without any repayment behaviour by the applicant."},
    {"id": "CB-TL-02", "name": "Inherited seasoning older than the credit file", "hard": False,
     "test": lambda a: seasoning_gap_months(a) >= 36 and _f(a, "n_au_tradelines") >= 1,
     "mitigation": "Confirm the relationship to the primary cardholder; family piggybacking is common and "
                   "legitimate, rented seasoning is not."},
    {"id": "CB-TL-03", "name": "Rapid score jump in 90 days", "hard": False,
     "test": lambda a: _f(a, "score_delta_90d") >= 60,
     "mitigation": "Check what moved the score (paid-down utilisation vs. new AU lines or removed "
                   "derogatories) before trusting it."},
    {"id": "CB-SW-01", "name": "Credit sweep: heavy dispute activity", "hard": False,
     "test": lambda a: _f(a, "disputes_90d") >= 4 or _f(a, "derogs_removed_90d") >= 3,
     "mitigation": "Request bureau reinvestigation outcomes; derogatories removed by mass disputes may "
                   "reappear and understate risk."},
    {"id": "CB-PKG-01", "name": "One device submitting many identities", "hard": False,
     "test": lambda a: _f(a, "device_identities_30d") >= 4,
     "mitigation": "Link analysis on the device; approval-package sellers run applications for many "
                   "buyers and hand over a login afterwards."},
    {"id": "CB-PKG-02", "name": "Income documents failed or show tampering", "hard": False,
     "test": lambda a: a.get("income_verification") == "failed" or _f(a, "doc_tamper_score") >= 0.5,
     "mitigation": "Verify income from payroll or bank data instead of uploaded pay stubs; packages ship "
                   "fake pay stubs."},
    {"id": "CB-PKG-03", "name": "High-value asset with unverified income", "hard": False,
     "test": lambda a: _f(a, "asset_price") >= 40000 and a.get("income_verification") != "verified",
     "mitigation": "Verify income and affordability before funding; sellers advertise approvals for "
                   "high-value cars the buyer cannot afford."},
    {"id": "CB-SHALLOW-01", "name": "Score-only decision on a thin file", "hard": False,
     "test": lambda a: (str(a.get("product")) in SHALLOW_PRODUCTS and _f(a, "file_age_months") < 24
                        and _f(a, "credit_score") >= 700 and a.get("ecbsv_status") == "not_run"
                        and a.get("income_verification") != "verified"),
     "mitigation": "Do not rely on the score alone for a young file; a premade CPN is sold with a "
                   "700-750+ score precisely because shallow checks stop there."},
    {"id": "CB-CONTACT-01", "name": "Brand-new phone and email", "hard": False,
     "test": lambda a: _f(a, "phone_age_days") < 90 and _f(a, "email_age_days") < 90,
     "mitigation": "Send one-time codes to contact points on file at the bureau, not the ones supplied."},
]

ECBSV_COST_NOTE = ("eCBSV is consent-based, returns yes/no only, and costs roughly $0.20-$0.50 per check "
                   "plus an annual tier fee, so it is routed only where risk justifies it.")


def red_flags(app: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [{"id": r["id"], "name": r["name"], "hard": r["hard"], "mitigation": r["mitigation"]}
            for r in RED_FLAGS if r["test"](app)]


def _tree_path(tree: Mapping[str, List], x: List[float], per: List[float]) -> float:
    """Flat LightGBM tree (feature < 0 = leaf, left when x <= threshold). Adds Saabas path
    contributions (child value - parent value) into `per`; returns the leaf value."""
    f, thr, left, right, val = tree["f"], tree["t"], tree["l"], tree["r"], tree["v"]
    i = 0
    while f[i] >= 0:
        c = left[i] if x[f[i]] <= thr[i] else right[i]
        per[f[i]] += val[c] - val[i]
        i = c
    return val[i]


class CreditBrain:
    def __init__(self, model: Optional[Dict[str, Any]]):
        self.model = model
        if model is not None and model.get("features") != FEATURES:
            raise ValueError("model feature list does not match featurize(); retrain the model")

    @classmethod
    def load(cls, path: Optional[os.PathLike] = None) -> "CreditBrain":
        p = Path(path or os.getenv("CREDIT_BRAIN_MODEL_PATH") or DEFAULT_MODEL_PATH)
        if not p.is_file():
            return cls(None)
        return cls(json.loads(p.read_text(encoding="utf-8")))

    @property
    def loaded(self) -> bool:
        return self.model is not None

    @property
    def version(self) -> Optional[str]:
        return self.model.get("model_version") if self.model else None

    def score(self, app: Mapping[str, Any]) -> tuple[float, List[Dict[str, Any]]]:
        m = self.model
        x = featurize(app)
        if "trees" in m:
            per = [0.0] * len(FEATURES)
            logit = m.get("tree_init", 0.0)
            for t in m["trees"]:
                logit += _tree_path(t, x, per)
            contribs = list(zip(per, FEATURES))
        else:
            contribs = []
            logit = m["intercept"]
            for name, v, mu, sd, w in zip(FEATURES, x, m["mean"], m["scale"], m["coef"]):
                c = w * (v - mu) / sd
                logit += c
                contribs.append((c, name))
        prob = 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, logit))))
        reasons = [{"feature": n, "contribution": round(c, 4)}
                   for c, n in sorted(contribs, reverse=True)[:4] if c > 0]
        return prob, reasons

    def assess(self, app: Mapping[str, Any]) -> Dict[str, Any]:
        flags = red_flags(app)
        hard = any(f["hard"] for f in flags)
        if not self.loaded:
            return self._build(app, None, [], flags, "manual_review",
                               "Credit model not loaded: failing closed to manual review.")
        prob, reasons = self.score(app)
        t = self.model["thresholds"]
        if hard or prob >= t["t_high"]:
            decision = "manual_review"
        elif prob >= t["t_low"]:
            decision = "step_up_verification"
        else:
            decision = "approve_standard_checks"
        return self._build(app, prob, reasons, flags, decision, None)

    def _build(self, app, prob, reasons, flags, decision, note):
        ids = {f["id"] for f in flags}
        checks: List[str] = []
        if decision != "approve_standard_checks":
            if app.get("ecbsv_status") == "not_run" and (ids & {"CB-CPN-01", "CB-SHALLOW-01"}
                                                          or decision == "manual_review"):
                checks.append("ecbsv_consent_ssn_verification")
            if app.get("income_verification") != "verified":
                checks.append("income_verification_from_payroll_or_bank_data")
            if ids & {"CB-TL-01", "CB-TL-02", "CB-TL-03"}:
                checks.append("rescore_excluding_authorized_user_tradelines")
            if "CB-SW-01" in ids:
                checks.append("review_bureau_dispute_outcomes")
            if "CB-PKG-01" in ids:
                checks.append("device_link_analysis")
        summary = note or (f"Fraud probability {prob:.3f}; {len(flags)} red flag(s): "
                           + (", ".join(f["name"] for f in flags) if flags else "none") + ".")
        return {
            "fraud_probability": None if prob is None else round(prob, 4),
            "decision": decision,
            "requires_human_review": decision == "manual_review",
            "auto_decline": False,
            "red_flags": flags,
            "reason_codes": reasons,
            "recommended_checks": checks,
            "verification_cost_note": ECBSV_COST_NOTE if "ecbsv_consent_ssn_verification" in checks else None,
            "model_version": self.version,
            "model_loaded": self.loaded,
            "summary": summary,
        }
