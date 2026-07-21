# CHIMERA Bank Platform

A locally runnable **defensive banking reference application**. It combines a
React/Vite dashboard with a Spring Boot API, a six-layer request-defense
pipeline, role-based local demo access, approved threat-intelligence sources,
and measurable CSV/RAG validation.

> This is a development demo, not a real bank. The ledger is in memory, resets
> on restart, has no payment-network integration, and must never be used with
> real money or production personal data.


```

## Local demo sign-in



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

