# CHIMERA Bank Platform
<img width="1107" height="911" alt="image" src="https://github.com/user-attachments/assets/693f1044-0f47-46cb-b360-52d6391fc7f1" />

A locally runnable **defensive banking reference application**. It combines a
React/Vite dashboard with a Spring Boot API, a six-layer request-defense
pipeline, role-based local demo access, approved threat-intelligence sources,
and measurable CSV/RAG validation.

> This is a development demo, not a real bank. The ledger is in memory, resets
> on restart, has no payment-network integration, and must never be used with
> real money or production personal data.
<img width="1667" height="825" alt="image" src="https://github.com/user-attachments/assets/074df453-2409-4f6f-a40e-6578c5101649" />


```
<img width="1470" height="622" alt="image" src="https://github.com/user-attachments/assets/c155fbf1-bd23-420d-9cf0-0f12239f2df6" />

 Local demo sign-in
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

The application does **not** ingest raw exploit code, scrape training labs, or
run attack payloads. RAG means document indexing/retrieval here; it is not a
claim that every underlying ML model has been retrained.
<img width="1883" height="920" alt="image" src="https://github.com/user-attachments/assets/baeec519-4e77-405b-8033-31f38079e9e8" />

