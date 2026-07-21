# CHIMERA Bank Platform

A locally runnable **defensive banking reference application**. It combines a
React/Vite dashboard with a Spring Boot API, a six-layer request-defense
pipeline, role-based local demo access, approved threat-intelligence sources,
and measurable CSV/RAG validation.

> This is a development demo, not a real bank. The ledger is in memory, resets
> on restart, has no payment-network integration, and must never be used with
> real money or production personal data.

## What is included

- React + Vite dashboard for **Client**, **Accountant**, and **Manager** roles.
- Local authenticated banking demo: account overview, transaction activity,
  deposit, withdrawal, transfer, credit-score display, and mutual-fund
  educational categories.
- Optional NIFTY quote adapter. It displays a price only when an approved,
  licensed endpoint is provided; it never fabricates a live value.
- The existing six defense rings screen client money-movement requests before
  the local ledger changes.
- Manager-controlled authorized CSV upload and independent defense validation
  with overall and per-layer **Pearson r**, **RMSE**, precision, recall, F1, and
  RAG self-healing recovery rate.
- RAG retrieval and evaluation based on MITRE ATT&CK technique context and
  structured CISA KEV / NVD vulnerability metadata.

## Run locally

### Option A: Docker Desktop

Start Docker Desktop first, then run:

```powershell
cd "C:\Users\acer\Documents\Sound Recordings\chimera-bank-platform"
docker compose up --build
```

Open <http://127.0.0.1:5173>. The API is also exposed at
<http://127.0.0.1:8080>.

### Option B: local frontend + API

The frontend is already configured for the API at `http://localhost:8080`.

```powershell
cd "C:\Users\acer\Documents\Sound Recordings\chimera-bank-platform\web"
npm install
npm run dev
```

Build the backend with Java 21+ and Maven from the project root:

```powershell
mvn clean test
mvn -pl platform-api spring-boot:run
```

## Local demo sign-in

| Dashboard role | Username | Password |
|---|---|---|
| Client | `client` | `demo-pass` |
| Accountant | `accountant` | `demo-pass` |
| Manager | `manager` | `demo-pass` |

The role selected in the sign-in form must match the demo user. Client role can
move funds in the in-memory ledger; staff roles are read-only in this demo.
Manager controls data upload, validation, and remote intelligence refresh.

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

The application does **not** ingest raw exploit code, scrape training labs, or
run attack payloads. RAG means document indexing/retrieval here; it is not a
claim that every underlying ML model has been retrained.

## Labeled validation workflow

1. Sign in as **Manager** and open **Evaluation**.
2. Upload an authorized `.csv` file. It is stored locally in
   `datasets/uploads/` (ignored by Git).
3. Select the uploaded file and map its fields.
   - `labelColumn`: label with malicious/fraud value.
   - `payloadColumn`: textual request/payload column.
   - For numeric transaction CSV data, set `payloadColumn` to `*`; non-label
     columns are serialized into a bounded feature string for evaluation.
   - `severityColumn` (optional): ground-truth score in `[0,1]`. Without it,
     malicious rows default to 0.8 and benign rows to 0.0, which is less useful
     for calibration analysis.
4. Run validation. The report presents per-layer health with Pearson r and RMSE
   plus retrieval/self-healing outcomes.

The manager can also open **Intelligence** and press **Refresh CISA + NVD**.
The refresh is intentionally manual, bounded, and resilient to unavailable
source services.

### RAG evaluation endpoint

Manager can supply human-reviewed retrieval test cases to:

```text
POST /api/intelligence/rag/evaluate
```

Example body:

```json
[
  {
    "query": "known exploited public-facing application",
    "expectedSource": "CISA KEV",
    "expectedTechniqueId": "T1190"
  }
]
```

It reports top-1 accuracy, top-3 recall, and MRR. Keep a held-out test set;
do not score only the same prompts used to create the knowledge entries.

## Important limits before any real deployment

Replace the demo authentication with an OIDC/SSO provider, MFA, hashed
credentials, secure sessions, persistent encrypted storage, accounting
controls, double-entry reconciliation, idempotency, transaction limits, KYC /
AML workflows, audit retention, an approved market-data licence, and a formal
model-governance process. Obtain security, legal, compliance, and financial
approval before connecting it to any real customer, account, or fund data.