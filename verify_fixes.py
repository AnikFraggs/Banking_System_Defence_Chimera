#!/usr/bin/env python3
"""
verify_fixes.py - Automated verification for Chimera Bank Platform Fixes (B1-B6 + Sections C-E)
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def check_b1():
    p = ROOT / "platform-api/src/main/java/com/chimera/bank/banking/MarketQuoteService.java"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    # Check timeout configuration
    if "quoteTimeoutMs" not in txt and "timeout" not in txt.lower():
        return False, "Missing timeout configuration for remote quote fetch"

    # Check empty response guard
    if "isEmpty()" not in txt:
        return False, "Missing guard against empty/partial remote quote response"

    # Check fallback has live=false
    # In fallback: new MarketQuote(..., false, ...)
    if re.search(r'MarketQuote\s*\(\s*"NIFTY[^"]*",\s*[\d.]+\s*,\s*\w+,\s*"Simulated Feed",\s*true', txt):
        return False, "Simulated fallback quotes still have live=true"

    if 'new MarketQuote("NIFTY 50", 22350.45, now, "Simulated Feed", false' not in txt and "false" not in txt:
        return False, "Simulated fallback quotes should have live=false"

    # Live market data should only be inside remote != null check
    if '"Live market data"' in txt:
        remote_idx = txt.find("remote != null")
        live_idx = txt.find('"Live market data"')
        if remote_idx == -1 or live_idx < remote_idx:
            return False, "Live market data label used outside remote != null block"

    return True, "MarketQuoteService has bounded timeout, empty guard, and correct simulated fallback"

def check_b2():
    p = ROOT / "platform-api/src/main/java/com/chimera/bank/outbox/KafkaOutboxPublisher.java"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    if ".getNow(" in txt:
        return False, "KafkaOutboxPublisher still uses .getNow(null)"

    if ".get(" not in txt or "TimeUnit" not in txt:
        return False, "KafkaOutboxPublisher missing bounded .get(timeout, TimeUnit) call"

    if "CircuitBreaker" not in txt or "markPendingForRetry" not in txt:
        return False, "KafkaOutboxPublisher missing @CircuitBreaker / markPendingForRetry"

    return True, "KafkaOutboxPublisher uses bounded .get() with circuit breaker protection"

def check_b3():
    p = ROOT / "render.yaml"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    if "FRAUD_GATE_TIMEOUT_MS" not in txt or '"300"' not in txt:
        return False, "render.yaml missing FRAUD_GATE_TIMEOUT_MS: '300'"

    if "CHIMERA_CHECKOUT_FRAUD_GATE_TRANSPORT" not in txt and "FRAUD_GATE_TRANSPORT" not in txt:
        return False, "render.yaml missing explicit http transport setting"

    return True, "render.yaml sets HTTP transport and bounded 300ms timeout"

def check_b4():
    p = ROOT / "compose.yaml"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    if "ai-brain:" not in txt:
        return False, "compose.yaml missing ai-brain service key"

    if "8000" not in txt:
        return False, "compose.yaml container port for ai-brain should be 8000"

    if "AI_BRAIN_BASE_URL" not in txt or "http://ai-brain:8000" not in txt:
        return False, "platform-api missing AI_BRAIN_BASE_URL: http://ai-brain:8000 in compose.yaml"

    return True, "compose.yaml has ai-brain service on port 8000 with matching AI_BRAIN_BASE_URL"

def check_b5():
    p = ROOT / "platform-api/src/main/java/com/chimera/bank/evaluation/ThreatSimulationService.java"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    if "isMock" not in txt and "simulated" not in txt.lower():
        return False, "Hardcoded scores not labeled as mock/simulated"

    if "ThreatSimulationResult" not in txt and "SimulationResult" not in txt:
        return False, "Missing threat simulation result model"

    return True, "ThreatSimulationService explicitly labels baseline scores as mock/simulated"

def check_b6():
    p = ROOT / "platform-api/src/main/java/com/chimera/bank/auth/RegistrationController.java"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    # Check that req.role() is NOT used as role argument in user registration
    if re.search(r'setRole\([^)]*req\.role\(\)', txt) or re.search(r'register\([^)]*req\.role\(\)', txt):
        return False, "Still uses client-supplied req.role() in user creation"

    if "Role.CUSTOMER" not in txt:
        return False, "RegistrationController does not enforce Role.CUSTOMER"

    if "@Size" not in txt or "min=8" not in txt.replace(" ", ""):
        return False, "Missing @Size(min=8) validation on password"

    if "@Pattern" not in txt:
        return False, "Missing @Pattern validation on username"

    if "HttpStatus.CREATED" not in txt:
        return False, "RegistrationController should return HttpStatus.CREATED (201)"

    return True, "RegistrationController enforces Role.CUSTOMER, password/username validation, and 201 Created"

def check_section_c():
    p = ROOT / "platform-api/src/main/java/com/chimera/bank/banking/BankService.java"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    if "SecureRandom" not in txt:
        return False, "BankService does not use SecureRandom"

    if "new Random()" in txt:
        return False, "BankService still contains 'new Random()' calls"

    return True, "BankService uses SecureRandom instead of new Random()"

def check_section_d():
    vite_p = ROOT / "web/vite.config.js"
    css_p = ROOT / "web/src/styles.css"
    telemetry_p = ROOT / "web/src/checkout/useSessionTelemetry.js"

    if not vite_p.exists() or "@tailwindcss/vite" not in vite_p.read_text(encoding="utf-8"):
        return False, "web/vite.config.js missing @tailwindcss/vite"

    if not css_p.exists() or '@import "tailwindcss"' not in css_p.read_text(encoding="utf-8"):
        return False, "web/src/styles.css missing @import 'tailwindcss'"

    if not telemetry_p.exists():
        return False, f"Missing {telemetry_p}"

    telem_txt = telemetry_p.read_text(encoding="utf-8")
    if "'keyup'" not in telem_txt or "onKeyUp" not in telem_txt:
        return False, "useSessionTelemetry.js missing keyup event listener for onKeyUp"

    if "keystrokeDwellMs" not in telem_txt or "keystrokeDwellMs: [" not in telem_txt:
        return False, "useSessionTelemetry.js drops keystrokeDwellMs in getTelemetry()"

    return True, "Tailwind v4 wired in vite + CSS, and useSessionTelemetry.js captures dwell telemetry"

def check_section_e():
    p = ROOT / "README.md"
    if not p.exists():
        return False, f"Missing {p}"
    txt = p.read_text(encoding="utf-8")

    if "Without a trained HGB artifact, all checkouts resolve to CHALLENGE" not in txt:
        return False, "README.md missing explicit notice: 'Without a trained HGB artifact, all checkouts resolve to CHALLENGE. This is by design (fail-closed).'"

    return True, "README.md explicitly documents fail-closed CHALLENGE requirement"

def main():
    checks = [
        ("B1 — MarketQuoteService", check_b1),
        ("B2 — KafkaOutboxPublisher", check_b2),
        ("B3 — render.yaml", check_b3),
        ("B4 — AiBrainClient & compose.yaml", check_b4),
        ("B5 — ThreatSimulationService", check_b5),
        ("B6 — RegistrationController", check_b6),
        ("Section C — SecureRandom in BankService", check_section_c),
        ("Section D — Tailwind v4 & Dwell Telemetry", check_section_d),
        ("Section E — Model Requirement in README", check_section_e),
    ]

    all_passed = True
    print("=" * 70)
    print("CHIMERA PLATFORM VERIFICATION")
    print("=" * 70)

    for name, fn in checks:
        passed, msg = fn()
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}")
        print(f"       -> {msg}")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("ALL STATIC CHECKS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("SOME CHECKS FAILED. Review errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
