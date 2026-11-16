"""Deterministic synthetic credit-application generator for the CHIMERA credit brain.

Typologies follow Resistant AI's "Credit boost fraud" research (21 Telegram channels,
13,900 messages): purchased authorized-user (AU) tradelines, credit sweeps that dispute
away accurate derogatories, CPN synthetic identities sold "premade" with a claimed
700-750+ score, and seller-operated "approval packages" (CPN + tradelines + fake pay
stubs, seller runs the application). Hard negatives model the legitimate look-alikes
that make these signals ambiguous: family AU piggybacking, newcomers with a recently
issued SSN, credit rebuilders filing accurate disputes, and genuine score improvers.

Everything is synthetic. No SSN, CPN, name or account-number strings are generated;
identity evidence is expressed only as derived features (first-seen age, eCBSV result).
Metrics on this data show the model recovers the generator's signal, not real-world
fraud-detection quality.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

GENERATOR_VERSION = "credit-boost-synth-v1"

PRODUCTS = ["credit_card", "bnpl", "personal_loan", "auto_loan", "apartment_rental", "mortgage"]
# Cheaper products get shallower checks; eCBSV costs ~$0.20-0.50/check plus a $5,100/yr tier
# fee, so institutions run it as a last resort (deeper for mortgages, rarely for rentals).
ECBSV_RUN_P = {"credit_card": 0.05, "bnpl": 0.02, "personal_loan": 0.20, "auto_loan": 0.15,
               "apartment_rental": 0.01, "mortgage": 0.50}
INCOME_VERIFY_RUN_P = {"credit_card": 0.25, "bnpl": 0.08, "personal_loan": 0.60, "auto_loan": 0.65,
                       "apartment_rental": 0.45, "mortgage": 0.97}
LEGIT_PRODUCT_P = [0.32, 0.22, 0.14, 0.12, 0.12, 0.08]

LEGIT_MIX = {"legit_prime": 0.52, "legit_thin_family_au": 0.14, "legit_newcomer": 0.10,
             "legit_rebuilder": 0.14, "legit_improver": 0.10}
FRAUD_MIX = {"fraud_tradeline_boost": 0.33, "fraud_credit_sweep": 0.20,
             "fraud_cpn_synthetic": 0.25, "fraud_approval_package": 0.22}

COLUMNS = [
    "app_id", "ring_id", "typology", "label", "product", "applicant_age", "id_first_seen_years_ago",
    "id_linked_other_identity", "id_deceased_record", "ecbsv_status", "credit_score",
    "score_delta_90d", "file_age_months", "n_tradelines", "n_au_tradelines", "au_added_90d",
    "oldest_tradeline_months", "au_total_limit", "unknown_furnisher_primaries", "disputes_90d",
    "derogs_removed_90d", "inquiries_6m", "stated_monthly_income", "income_verification",
    "doc_tamper_score", "requested_amount", "asset_price", "address_matches_bureau",
    "phone_age_days", "email_age_days", "device_identities_30d",
]


def _clip(v, lo, hi):
    return float(min(max(v, lo), hi))


def _amounts(rng, product, income):
    if product == "credit_card":
        return float(rng.uniform(500, 15000)), 0.0
    if product == "bnpl":
        return float(rng.uniform(50, 2000)), 0.0
    if product == "personal_loan":
        return float(rng.uniform(1000, 40000)), 0.0
    if product == "auto_loan":
        price = float(rng.uniform(12000, 60000))
        return price * float(rng.uniform(0.7, 1.0)), price
    if product == "apartment_rental":
        rent = _clip(income * rng.uniform(0.2, 0.4), 700, 6000)
        return rent * 12, 0.0
    price = float(rng.uniform(150000, 750000))
    return price * float(rng.uniform(0.75, 0.95)), price


def _verification(rng, product, fake_docs, adaptive):
    if rng.random() >= INCOME_VERIFY_RUN_P[product]:
        status = "not_run"
    elif fake_docs:
        status = "failed" if rng.random() < (0.55 if adaptive else 0.8) else "verified"
    else:
        status = "failed" if rng.random() < 0.02 else "verified"
    return status


def _ecbsv(rng, product, synthetic_id, boost=1.0):
    if rng.random() >= min(1.0, ECBSV_RUN_P[product] * boost):
        return "not_run"
    if synthetic_id:
        return "no_match" if rng.random() < 0.92 else "match"
    # Legit mismatches happen (name change, typo, consent data error): a real hard negative.
    return "no_match" if rng.random() < 0.03 else "match"


def _base_legit(rng, kind, product):
    """A genuine applicant. Returns a dict of raw fields."""
    if kind == "legit_thin_family_au":
        age = float(rng.uniform(18, 25))
        first_seen = _clip(age - 18 + rng.uniform(-0.5, 0.5), 0.2, 7)
    elif kind == "legit_newcomer":
        age = float(rng.uniform(24, 52))
        first_seen = float(rng.uniform(0.4, 4.0))  # recently issued SSN, adult applicant
    else:
        age = float(rng.uniform(24, 72))
        first_seen = _clip(age - 18 - rng.uniform(0, 4), 0.5, 60)
    file_age = first_seen * 12 * float(rng.uniform(0.85, 1.0))

    if kind == "legit_rebuilder":
        score = rng.normal(605, 45)
        delta = rng.normal(8, 22)
    elif kind == "legit_improver":
        score = rng.normal(700, 35)
        delta = rng.uniform(35, 95)  # paid down utilisation: a genuine rapid score jump
    elif kind == "legit_newcomer":
        score = rng.normal(688, 38)
        delta = rng.normal(5, 15)
    elif kind == "legit_thin_family_au":
        score = rng.normal(690, 45)
        delta = rng.normal(5, 20)
    else:
        score = rng.normal(738, 45)
        delta = rng.normal(0, 14)

    n_trade = int(rng.poisson(1.5 if kind in ("legit_newcomer", "legit_thin_family_au") else 7)) + 1
    n_au, au_added, au_limit = 0, 0, 0.0
    oldest = file_age * float(rng.uniform(0.8, 1.0))
    if kind == "legit_thin_family_au" and rng.random() < 0.7:
        n_au = int(rng.integers(1, 3))
        au_added = int(rng.random() < 0.2)
        oldest = file_age + float(rng.uniform(60, 220))  # inherited seasoning from a parent's card
        au_limit = float(rng.uniform(3000, 25000)) * n_au
    elif rng.random() < 0.10:
        n_au = 1
        au_added = int(rng.random() < 0.08)
        au_limit = float(rng.uniform(2000, 20000))
        if rng.random() < 0.3:
            oldest = max(oldest, file_age + float(rng.uniform(12, 120)))  # spouse's older card
    n_trade = max(n_trade, n_au)

    disputes = int(rng.poisson(1.2 if kind == "legit_rebuilder" else 0.08))
    removed = int(rng.binomial(disputes, 0.35)) if disputes else 0
    income = float(rng.lognormal(np.log(4200 if kind == "legit_thin_family_au" else 6000), 0.45))
    requested, asset = _amounts(rng, product, income)
    docs = rng.random() < 0.5
    return {
        "applicant_age": round(age, 1),
        "id_first_seen_years_ago": round(first_seen, 2),
        "id_linked_other_identity": int(rng.random() < 0.004),
        "id_deceased_record": int(rng.random() < 0.0005),
        "ecbsv_status": _ecbsv(rng, product, synthetic_id=False),
        "credit_score": int(_clip(round(score), 300, 850)),
        "score_delta_90d": int(round(delta)),
        "file_age_months": int(round(file_age)),
        "n_tradelines": n_trade,
        "n_au_tradelines": n_au,
        "au_added_90d": au_added,
        "oldest_tradeline_months": int(round(oldest)),
        "au_total_limit": round(au_limit, 2),
        "unknown_furnisher_primaries": int(rng.random() < 0.01),
        "disputes_90d": disputes,
        "derogs_removed_90d": removed,
        "inquiries_6m": int(rng.poisson(2.6 if kind == "legit_rebuilder" else 1.1)),
        "stated_monthly_income": round(income, 2),
        "income_verification": _verification(rng, product, fake_docs=False, adaptive=False),
        "doc_tamper_score": round(float(rng.beta(1.2, 30)) if docs else 0.0, 4),
        "requested_amount": round(requested, 2),
        "asset_price": round(asset, 2),
        "address_matches_bureau": int(rng.random() < (0.82 if kind == "legit_newcomer" else 0.94)),
        "phone_age_days": int(rng.uniform(20, 900) if kind == "legit_newcomer" and rng.random() < 0.4
                              else rng.lognormal(np.log(1800), 0.7)),
        "email_age_days": int(rng.uniform(20, 900) if kind == "legit_newcomer" and rng.random() < 0.4
                              else rng.lognormal(np.log(2500), 0.7)),
        # Households and shared family devices legitimately see 2-3 identities.
        "device_identities_30d": int(1 + (rng.integers(1, 3) if rng.random() < 0.07 else 0)),
    }


def _ring_style(rng, kind, adaptive):
    """Seller-level parameters shared by every application a ring submits."""
    return {
        "target_score": float(rng.uniform(700, 765)),
        "au_lines": int(rng.integers(1 if adaptive else 2, 7)),
        "devices": int(rng.integers(5, 40)) if kind == "fraud_approval_package" else int(rng.integers(1, 3)),
        "doc_quality": float(rng.uniform(0.3, 0.9)),
        "product": rng.choice(["auto_loan", "apartment_rental", "personal_loan", "credit_card"],
                              p=[0.45, 0.35, 0.10, 0.10]) if kind == "fraud_approval_package"
        else rng.choice(PRODUCTS, p=LEGIT_PRODUCT_P),
    }


def _fraud(rng, kind, style, adaptive):
    if kind in ("fraud_tradeline_boost", "fraud_credit_sweep"):
        # Real identity, manipulated file.
        base_kind = "legit_rebuilder" if kind == "fraud_credit_sweep" or rng.random() < 0.5 else "legit_prime"
        product = style["product"] if rng.random() < 0.6 else rng.choice(PRODUCTS, p=LEGIT_PRODUCT_P)
        row = _base_legit(rng, base_kind, product)
        row["product"] = product
        if kind == "fraud_tradeline_boost":
            # AU slots priced $119-$261 by limit band; aged lines carry their seasoning.
            lines = max(1, style["au_lines"] + int(rng.integers(-1, 2)))
            spread = adaptive and rng.random() < 0.6  # adaptive buyers stagger purchases
            row["n_au_tradelines"] = row["n_au_tradelines"] + lines
            row["n_tradelines"] = row["n_tradelines"] + lines
            row["au_added_90d"] = int(rng.integers(0, 2)) if spread else lines
            row["au_total_limit"] = round(row["au_total_limit"] + float(
                sum(rng.choice([7500, 15000, 25000, 40000, 60000]) for _ in range(lines))), 2)
            row["oldest_tradeline_months"] = max(row["oldest_tradeline_months"],
                                                 row["file_age_months"] + int(rng.uniform(36, 200)))
            jump = rng.uniform(25, 80) if adaptive else rng.uniform(45, 150)
            row["score_delta_90d"] = int(jump)
            row["credit_score"] = int(_clip(row["credit_score"] + jump * 0.7, 300, 850))
        else:
            # Credit sweep: dispute accurate negatives ($100-$1,500) until they drop off.
            row["disputes_90d"] = int(rng.integers(2, 9) if adaptive else rng.integers(4, 25))
            row["derogs_removed_90d"] = int(min(row["disputes_90d"], rng.integers(2, 12)))
            jump = rng.uniform(30, 90) if adaptive else rng.uniform(40, 130)
            row["score_delta_90d"] = int(jump)
            row["credit_score"] = int(_clip(row["credit_score"] + jump * 0.8, 300, 850))
            row["inquiries_6m"] += int(rng.poisson(1.5))
        return row

    # CPN synthetic identity (optionally inside a seller-operated approval package).
    package = kind == "fraud_approval_package"
    product = style["product"] if package or rng.random() < 0.7 else rng.choice(PRODUCTS, p=LEGIT_PRODUCT_P)
    age = float(rng.uniform(24, 56))
    first_seen = float(rng.uniform(2.0, 5.0) if adaptive else rng.uniform(0.2, 2.5))  # aged CPNs when adaptive
    file_age = first_seen * 12 * float(rng.uniform(0.9, 1.0))
    lines = max(1, style["au_lines"] + int(rng.integers(-1, 2)))
    primaries = int(rng.integers(0, 3)) if rng.random() < 0.45 else 0
    income = float(rng.lognormal(np.log(9500 if package else 6500), 0.4))  # inflated stated income
    requested, asset = _amounts(rng, product, income)
    if package and product == "auto_loan":
        asset = float(rng.uniform(45000, 120000))  # "Got him approved for this Tesla"
        requested = asset * float(rng.uniform(0.8, 1.0))
    fake_docs = package or rng.random() < 0.3
    docs = fake_docs or rng.random() < 0.5
    tamper = rng.beta(2, 5) if adaptive else rng.beta(5, 3) * (0.6 + 0.4 * style["doc_quality"])
    return {
        "product": product,
        "applicant_age": round(age, 1),
        "id_first_seen_years_ago": round(first_seen, 2),
        "id_linked_other_identity": int(rng.random() < (0.2 if adaptive else 0.35)),
        "id_deceased_record": int(rng.random() < 0.06),
        "ecbsv_status": _ecbsv(rng, product, synthetic_id=True),
        "credit_score": int(_clip(rng.normal(style["target_score"], 15), 300, 850)),
        "score_delta_90d": int(rng.uniform(20, 140)),
        "file_age_months": int(round(file_age)),
        "n_tradelines": lines + primaries + int(rng.integers(0, 2)),
        "n_au_tradelines": lines,
        "au_added_90d": int(rng.integers(0, 2)) if adaptive else int(min(lines, rng.integers(1, lines + 1))),
        "oldest_tradeline_months": int(round(file_age + rng.uniform(48, 240))),
        "au_total_limit": round(float(sum(rng.choice([7500, 15000, 25000, 40000, 60000])
                                          for _ in range(lines))), 2),
        "unknown_furnisher_primaries": primaries,
        "disputes_90d": int(rng.poisson(0.3)),
        "derogs_removed_90d": 0,
        "inquiries_6m": int(rng.poisson(3.0)),
        "stated_monthly_income": round(income, 2),
        "income_verification": _verification(rng, product, fake_docs=fake_docs, adaptive=adaptive),
        "doc_tamper_score": round(float(tamper) if docs else 0.0, 4),
        "requested_amount": round(requested, 2),
        "asset_price": round(asset, 2),
        "address_matches_bureau": int(rng.random() < (0.7 if adaptive else 0.5)),
        "phone_age_days": int(rng.uniform(5, 200) if rng.random() < (0.35 if adaptive else 0.6)
                              else rng.lognormal(np.log(1200), 0.8)),
        "email_age_days": int(rng.uniform(5, 200) if rng.random() < (0.35 if adaptive else 0.6)
                              else rng.lognormal(np.log(1500), 0.8)),
        "device_identities_30d": int(rng.integers(1, 4)) if adaptive and package
        else max(1, style["devices"] + int(rng.integers(-2, 3))),
    }


def generate(n_rows: int, fraud_rate: float, seed: int, adaptive: bool = False,
             label_noise: float = 0.004) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    n_fraud = int(round(n_rows * fraud_rate))
    prefix = "A" if adaptive else "M"

    kinds = list(LEGIT_MIX)
    for i in range(n_rows - n_fraud):
        kind = kinds[int(rng.choice(len(kinds), p=list(LEGIT_MIX.values())))]
        product = str(rng.choice(PRODUCTS, p=LEGIT_PRODUCT_P))
        row = _base_legit(rng, kind, product)
        row.update(app_id=f"{prefix}L{i:06d}", ring_id=f"{prefix}L{i:06d}", typology=kind, label=0,
                   product=product)
        rows.append(row)

    fkinds = list(FRAUD_MIX)
    made, ring = 0, 0
    while made < n_fraud:
        kind = fkinds[int(rng.choice(len(fkinds), p=list(FRAUD_MIX.values())))]
        style = _ring_style(rng, kind, adaptive)
        size = int(min(n_fraud - made, 1 + rng.poisson(12 if kind == "fraud_approval_package" else 5)))
        for _ in range(size):
            row = _fraud(rng, kind, style, adaptive)
            row.update(app_id=f"{prefix}F{made:06d}", ring_id=f"{prefix}R{ring:05d}", typology=kind, label=1)
            rows.append(row)
            made += 1
        ring += 1

    for row in rows:  # investigation outcomes are imperfect
        if rng.random() < label_noise:
            row["label"] = 1 - row["label"]
    order = rng.permutation(len(rows))
    return [rows[i] for i in order]


def assign_split(ring_id: str) -> str:
    """Ring-grouped split so one seller's applications never straddle train and test."""
    bucket = int(hashlib.sha256(ring_id.encode()).hexdigest(), 16) % 100
    return "train" if bucket < 60 else ("val" if bucket < 80 else "test")


def write_csv(rows: list[dict], path: Path, with_split: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = COLUMNS + (["split"] if with_split else [])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            out = {c: r[c] for c in COLUMNS}
            if with_split:
                out["split"] = assign_split(r["ring_id"])
            w.writerow(out)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="datasets/synthetic_credit_boost")
    ap.add_argument("--rows", type=int, default=40000)
    ap.add_argument("--adaptive-rows", type=int, default=10000)
    ap.add_argument("--fraud-rate", type=float, default=0.07)
    ap.add_argument("--seed", type=int, default=20261113)
    a = ap.parse_args(argv)

    out = Path(a.out)
    main_rows = generate(a.rows, a.fraud_rate, a.seed)
    adaptive_rows = generate(a.adaptive_rows, a.fraud_rate, a.seed + 1, adaptive=True)
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": a.seed,
        "fraud_rate": a.fraud_rate,
        "files": {
            "credit_apps.csv": {"rows": len(main_rows),
                                "sha256": write_csv(main_rows, out / "credit_apps.csv", True)},
            "credit_apps_adaptive.csv": {"rows": len(adaptive_rows),
                                         "sha256": write_csv(adaptive_rows, out / "credit_apps_adaptive.csv",
                                                             False)},
        },
        "synthetic": True,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
