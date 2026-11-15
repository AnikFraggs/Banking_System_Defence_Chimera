
<img width="1107" height="911" alt="image" src="https://github.com/user-attachments/assets/693f1044-0f47-46cb-b360-52d6391fc7f1" />
# CHIMERA Bank Platform

A locally runnable **defensive banking reference application**. It pairs a real
banking workflow (accounts, payments, an approval pipeline, market data) with a
**six-layer, self-healing request-defense pipeline** and a **GenAI cybersecurity
triage brain** — then *measures* how well that defense actually works against a
203-sample adversarial battery.

> ⚠️ This is a development demo, not a real bank. The ledger is in memory / a
> local Postgres, resets on restart, has no payment-network settlement, and must
> never be used with real money or production personal data. All "attacks" run
> against the platform's **own** pipeline in a local sandbox.

---

<img width="1667" height="825" alt="image" src="https://github.com/user-attachments/assets/074df453-2409-4f6f-a40e-6578c5101649" />



<img width="1470" height="622" alt="image" src="https://github.com/user-attachments/assets/c155fbf1-bd23-420d-9cf0-0f12239f2df6" />

 
<img width="1153" height="891" alt="image" src="https://github.com/user-attachments/assets/5f645b8f-e42f-4908-8a96-a988b5bcee32" />
<img width="752" height="832" alt="image" src="https://github.com/user-attachments/assets/0d853598-fcf9-45ca-a70e-5cbc1c31cbec" />(libetransactions between clients using B2B callls from databses through the secure 6 layer paipeline without leakage)
<img width="860" height="893" alt="image" src="https://github.com/user-attachments/assets/1365d23d-fdbb-4505-9412-620a0839a29c" />(allowing clients to take suggestions from their accountant before investing in different stocks and the potential risk in mutual funds)





## Data and intelligence policy

| Source | Use in this project | Mode |
|---|---|---|
| [Kaggle](https://www.kaggle.com/datasets) | Operator-provided labeled CSV for validation | Local upload only; check licence and authorization first |
| [MITRE ATT&CK](https://attack.mitre.org/) | Standardized technique mapping | Curated defensive technique taxonomy |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Known-exploited vulnerability prioritization | Manager-triggered structured JSON refresh |
| [NVD CVE API](https://nvd.nist.gov/developers/vulnerabilities) | CVE/CVSS enrichment | Manager-triggered structured JSON refresh |
| [OWASP](https://owasp.org/) | Defensive guidance | Reference link only |
| [PortSwigger Web Security Academy](https://portswigger.net/web-security) | Authorized learning reference | Reference link only; never scraped |
| [OWASP Juice Shop](https://owasp.org/www-project-juice-shop/) | Local practice-app reference | Reference link only |


<img width="1883" height="920" alt="image" src="https://github.com/user-attachments/assets/baeec519-4e77-405b-8033-31f38079e9e8" />


## 1. What's inside (architecture)

CHIMERA is a polyglot, multi-module system. Each service does one job and can be
built and reasoned about on its own.

| Module | Stack | Responsibility |
|---|---|---|
| `platform-api` | Spring Boot 3.3.5, Java 21, JPA → Postgres | Auth, banking ledger, service-requests, suggestions, market quotes, and the proxy into the defense + AI brain |
| `defense-pipeline` | Pure Java (no framework lock-in) | The six-layer defense, self-healing controller, deception vault, red-team battery, and the metrics/validation harness |
| `common` | Java | Shared RBAC (`Role`: CUSTOMER, ACCOUNTANT, MANAGER) and the `DefenseContext` / `LayerVerdict` contracts |
| `web` | React 18 + Vite + Tailwind | Role-routed dashboard, live market chart, payment surfaces |
| `bff-express` | Node/Express | Memory-hierarchy BFF demo (VRAM → Redis → Postgres) |
| `ai-brain` | Python FastAPI | GenAI-style cybersecurity triage: feature-weighted risk model + RAG knowledge base of attack classes with mitigations |
| `compose.yaml` | Docker Compose | Wires all six services + Postgres + Redis |

### The six rings of defense

Requests flow **outermost → innermost**. The pipeline short-circuits on the first
terminal verdict, so an attacker never reaches an inner ring once an outer one has
contained them. Every ring's verdict is retained for a full audit trail.

| Ring | Layer | Catches |
|---|---|---|
| L1 | IP reputation | Denylisted / malformed / missing source IPs |
| L2 | Role + status | RBAC privilege escalation (e.g. a CUSTOMER attempting a MANAGER action) |
| L3 | Purpose | Intent tampering — payload that doesn't match the declared purpose; unknown purposes |
| L4 | Injection & leak | Prompt injection, canary-token exfiltration, and **evasion variants**: homoglyph/confusable text, zero-width & bidi Unicode stego, nested base64 |
| L5 | Human verification | Anti-automation step-up (valid request, no human challenge passed) |
| L6 | Deception vault | Relocates a session's working set into an isolated honeypot when healing fails |

### The self-healing loop

The `DefenseOrchestrator` runs the loop the design calls for on every request:

```
face the attacker → run every ring (prevent) → on a raised threat, RAG self-heal
the compromised layer → if heal fails, contain in the deception vault → record
the outcome for the report
```

- A hard **BLOCK** (RBAC violation, denylisted IP) is a policy decision and stays blocked.
- A **CHALLENGE / QUARANTINE** triggers bounded, RAG-driven remediation. If it heals, the session is allowed-with-controls (**REMEDIATED**). If it can't, the session is **VAULTED**.
- A layer that throws **fails safe to CHALLENGE** — never an implicit pass.

---

## 2. How to run it

### Option A — full stack with Docker (recommended)

```powershell
cd "C:\Users\acer\Documents\Sound Recordings\chimera-bank-platform"
docker compose up --build
```

Then open:

| URL | Service |
|---|---|
| http://localhost:5173 | React dashboard |
| http://localhost:8080 | platform-api (Spring Boot) |
| http://localhost:8080/swagger-ui.html | API docs |
| http://localhost:8000/health | AI brain health |
| http://localhost:5000 | Express BFF demo |

The manager key defaults to `manager-local-key` (override with `MANAGER_AUTH_KEY`).

### Option B — build & verify **without Maven** (this dev box)

This box has JDK 23 but no Maven, so the Java modules are verified directly with
`javac`/`java` against the local `~/.m2` classpath. The pre-built argfiles live in
`build-check/`.

```powershell
$java = "C:\Program Files\Java\jdk-23\bin\java.exe"
$bc   = "C:\Users\acer\Documents\Sound Recordings\chimera-bank-platform\build-check"

# Run the full defense + red-team + validation test suite
& $java "@$bc\java-tests.args"
```

Frontend:

```powershell
cd web
npm.cmd install
npm.cmd run build     # ~3s Vite build
```

> On this machine the Cygwin `bash` tool has fork issues — use **PowerShell** for
> build/verify steps.

---

## 3. Headline results — the part that makes a résumé stand out

These are **measured**, reproducible outputs from `build-check\java-tests.args`
(run 2026-07-22, JDK 23), not aspirational targets. Everything below comes straight
from the test console.

### 3.1 Full test suite

```
Tests: 17 passed, 0 failed
```

### 3.2 Adversarial battery (203 labeled samples: 155 malicious, 48 benign)

```
Confusion  TP=155  TN=48  FP=0  FN=0
Accuracy = 1.0000   Precision = 1.0000   Recall = 1.0000   F1 = 1.0000
Severity calibration: Pearson r = 0.9380   RMSE = 0.1552
RAG recovery rate    = 66.7%  (48 remediated / 72 healing-triggered)
```

- **Zero missed attacks and zero false positives** across 203 samples spanning
  homoglyph evasion, split/re-delimited canaries, nested base64, zero-width & bidi
  Unicode stego, RBAC escalation, intent tampering, and network denylisting.
- **Severity is calibrated, not just binary** — predicted threat severity correlates
  with ground truth at **r = 0.94**. The system doesn't just say "bad," it says
  "how bad," which is what drives the block/challenge/step-up decision.

### 3.3 Per-layer health readout

```
layer                    n   recall precision   rmse      r   health%
L1_ip_reputation         3    1.000    1.000   0.000  1.000    100.0%
L2_role_status          11    1.000    1.000   0.078  0.000     81.1%
L3_purpose               4    1.000    1.000   0.000  0.000     82.5%
L4_injection_leak      131    1.000    1.000   0.192  0.695     91.3%
L5_human_verification    6    1.000    1.000   0.000  1.000    100.0%
benign (no-fire)        48    1.000    1.000   0.000  0.000     82.5%
```

### 3.4 Red-team walk-through (one attack per ring)

```
A1 Denylisted-IP intrusion (L1)   → BLOCKED   sev 0.95
A2 Privilege escalation (L2)      → BLOCKED   sev 0.85
A3 Intent tampering (L3)          → REMEDIATED (self-heal, 2 rounds, residual 0.19)
A4 Injection + zero-width stego   → BLOCKED   sev 0.94
A5 Canary-leak, heal fails (L4→L6)→ VAULTED  (heal failed after 3 rounds → honeypot)
```

### Why these are differentiators vs. what big banks typically ship

Most production bank stacks bolt security on as *infrastructure* — a WAF, an SIEM,
a fraud-scoring vendor — with detection logic living in opaque appliances and
effectiveness reported quarterly, if at all. CHIMERA demonstrates several things
that are genuinely uncommon in that world and make strong résumé talking points:

1. **Defense-in-depth that is code you can read and test**, not a black-box appliance.
   Six ordered rings with explicit, auditable verdicts.
2. **A self-healing / auto-remediation loop.** Threats aren't just blocked — the
   system attempts bounded RAG-guided remediation and only escalates to isolation
   when that fails. Most banks have humans in that loop; here it's measured and automatic.
3. **A deception vault (honeypot) as a first-class control.** Sessions that can't be
   healed are relocated to an isolated trap rather than hard-failed — an active-defense
   technique rarely wired into a retail banking request path.
4. **Unicode-evasion detection built in** — homoglyph/confusable folding, zero-width
   and bidi Trojan-Source stego, nested base64. These are exactly the bypasses that
   defeat naive keyword/WAF filters, and the battery proves they're caught at 100% recall.
5. **Security effectiveness is a unit test.** The pipeline ships with a 203-sample
   adversarial battery and a metrics harness (recall, precision, F1, Pearson r, RMSE,
   per-layer health%). Security posture is a number that regressions can break — a
   level of continuous, quantified assurance most banks don't have on their detection logic.
6. **A GenAI triage brain that runs fully offline** and returns an explainable verdict
   (risk score + MITRE-style technique ID + a concrete mitigation the manager can act on),
   degrading gracefully to a local fallback if the brain is unreachable.
7. **Approval-gated money movement by design.** A client can view and *suggest*, but
   invest/deposit/loan/buy all flow through a `ServiceRequest` (PENDING → accountant
   APPROVE/REJECT). Approval is the *only* path that moves money — separation of duties
   enforced in the domain model, not just in a policy document.

**One-line résumé framing:**
> Built a polyglot defensive banking platform whose six-layer, self-healing request
> pipeline detects Unicode-evasion and prompt-injection attacks at **100% recall /
> 0 false positives** over a 203-sample adversarial battery (severity calibration
> Pearson r = 0.94), with automated RAG remediation, a deception-vault fallback, and
> security effectiveness enforced as a passing test suite.

---

## 4. Roadmap — what to change to make this one of the best banking platforms on earth

The results above are strong *because the battery is deterministic and self-authored*.
The honest next steps are about turning a convincing reference implementation into
something production-credible. In rough priority order:

### Correctness & trust
- **Persistent, double-entry ledger.** Replace the in-memory/reset ledger with an
  append-only, double-entry accounting core (every debit has a matching credit),
  idempotency keys on every mutation, and reconciliation jobs. This is the single
  biggest gap between a demo and a bank.
- **Real authn/authz.** Swap the local demo sign-in for OIDC/OAuth2 + MFA, short-lived
  tokens, and step-up (WebAuthn/passkeys) wired into the L5 human-verification ring.
- **Exactly-once payments.** Idempotent payment intents, a saga/outbox pattern for
  distributed consistency, and integration with a real (sandboxed) payment rail.

### Making the defense metrics believable to an outsider
- **Externally-sourced, held-out evaluation.** The current 100%/0-FP result is on a
  battery the same team wrote. Add independent, labeled corpora (e.g. curated public
  attack datasets), an adversary who has *not* seen the detectors, and report on a
  held-out split so numbers can't be over-fit.
- **Adversarial ML / fuzzing loop.** Continuously generate novel evasions
  (mutation-based fuzzing, LLM-generated attack variants) and track recall over time,
  not just against a fixed set.
- **Latency & throughput SLOs.** The pipeline already records per-layer latency —
  publish p50/p95/p99 under load and a throughput ceiling, since a defense that
  can't keep up with traffic isn't deployable.

### Operational maturity
- **Real observability.** OpenTelemetry traces per correlation ID across all six
  services, structured audit log shipped to an immutable store, and dashboards for
  block/challenge/vault rates.
- **Threat-intel freshness.** Wire the (already-scaffolded) CISA KEV / NVD / MITRE
  ATT&CK refreshers into scheduled, signed updates with provenance tracking.
- **Upgrade the AI brain.** The heuristic + regex-RAG model is a fine offline default;
  make it pluggable so a fine-tuned classifier or a hosted LLM can slot in, with the
  heuristic remaining the guaranteed fallback.

### Correctness of the self-heal loop
- **Bound and prove remediation safety.** Formalize what "healed" is allowed to do
  (it must never widen access), add invariants/property tests around it, and make the
  deception-vault interaction resistant to an attacker who *wants* to be vaulted.

### Platform hardening
- Secrets management (no default `manager-local-key` / `pass`), per-service least-privilege
  DB roles, network segmentation between rings, dependency/SBOM scanning in CI, and a
  real CI pipeline that runs the adversarial battery on every commit and **fails the
  build if recall drops or false positives appear**.

---

## Data & intelligence policy

| Source | Use here | Mode |
|---|---|---|
| [MITRE ATT&CK](https://attack.mitre.org/) | Technique taxonomy | Curated defensive mapping |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Known-exploited-vuln prioritization | Manager-triggered structured refresh |
| [NVD CVE API](https://nvd.nist.gov/developers/vulnerabilities) | CVE/CVSS enrichment | Manager-triggered structured refresh |
| [OWASP](https://owasp.org/) | Defensive guidance | Reference only |
| Kaggle | Operator-provided labeled CSV for validation | Local upload only; check licence & authorization first |

The application does **not** ingest raw exploit code, scrape labs, or run attack
payloads against external systems. "RAG" here means document indexing/retrieval of
attack-class signatures and mitigations — not a claim that any underlying model has
been retrained.
